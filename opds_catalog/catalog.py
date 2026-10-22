"""
catalog.py — Zachary Rosario

Query builder and database access for the OPDS feed, backed by the
mv_books_dc materialized view.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple, Union

from sqlalchemy import (
    Column,
    Date,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    cast,
    column,
    exists,
    func,
    literal,
    literal_column,
    null,
    select,
    table,
    text,
    true,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.sql.expression import Select

from .constants import (
    Crosswalk,
    CuratedBookshelves,
    OrderBy,
    SearchField,
    SortDirection,
)
from .publications import CROSSWALK_MAP

__all__ = [
    "Catalog",
    "CatalogQuery",
]

# =============================================================================
# Tables
# =============================================================================

_metadata = MetaData()

mv_books_dc = Table(
    "mv_books_dc",
    _metadata,
    Column("book_id", Integer, primary_key=True),
    Column("title", Text),
    Column("tsvec", TSVECTOR),
    Column("downloads", Integer),
    Column("release_date", Date),
    Column("copyrighted", Integer),
    Column("book_text", Text),
    Column("lang_codes", ARRAY(Text)),
    Column("locc_codes", ARRAY(String)),
    Column("creator_ids", ARRAY(Integer)),
    Column("creator_names", ARRAY(String)),
    Column("creator_roles", ARRAY(String)),
    Column("creator_born_floor", ARRAY(Integer)),
    Column("creator_born_ceil", ARRAY(Integer)),
    Column("creator_died_floor", ARRAY(Integer)),
    Column("creator_died_ceil", ARRAY(Integer)),
    Column("subject_ids", ARRAY(Integer)),
    Column("subject_names", ARRAY(String)),
    Column("bookshelf_ids", ARRAY(Integer)),
    Column("bookshelf_names", ARRAY(Text)),
    Column("dcmitypes", ARRAY(Text)),
    Column("publisher", Text),
    Column("summary", ARRAY(Text)),
    Column("reading_level", Text),
    Column("format_filenames", ARRAY(String)),
    Column("format_filetypes", ARRAY(String)),
    Column("format_hr_filetypes", ARRAY(String)),
    Column("format_mediatypes", ARRAY(String)),
    Column("format_extents", ARRAY(Integer)),
    Column("filemtime"),
)
_mv = mv_books_dc.c

_mn_books_authors = table("mn_books_authors", column("fk_books"), column("fk_authors"))
_mn_books_subjects = table("mn_books_subjects", column("fk_books"), column("fk_subjects"))
_mn_books_bookshelves = table(
    "mn_books_bookshelves", column("fk_books"), column("fk_bookshelves")
)
_mn_books_loccs = table("mn_books_loccs", column("fk_books"), column("fk_loccs"))
_subjects = table("subjects", column("pk"), column("subject"))
_loccs = table("loccs", column("pk"), column("locc"))
_also_downloads = table(
    "also_downloads", column("id"), column("fk_books"), schema="scores"
)

# (tsvector expression, plain text expression) per searchable field
_FIELD_COLS = {
    SearchField.BOOK: (_mv.tsvec, _mv.book_text),
    SearchField.TITLE: (func.to_tsvector("english", _mv.title), _mv.title),
    SearchField.AUTHOR: (
        func.to_tsvector("english", func.array_to_string(_mv.creator_names, " ")),
        func.array_to_string(_mv.creator_names, " "),
    ),
}

# (column, default direction, nulls last)
_ORDER_COLUMNS = {
    OrderBy.DOWNLOADS: (_mv.downloads, SortDirection.DESC, False),
    OrderBy.TITLE: (_mv.title, SortDirection.ASC, False),
    OrderBy.AUTHOR: (_mv.creator_names[1], SortDirection.ASC, True),
    OrderBy.RELEASE_DATE: (_mv.release_date, SortDirection.DESC, True),
    OrderBy.FILEMTIME: (_mv.filemtime, SortDirection.DESC, True),
}

_OPDS_SMALL_COLUMNS = [
    _mv.book_id, _mv.title, _mv.lang_codes,
    _mv.creator_ids, _mv.creator_names, _mv.creator_roles,
    _mv.format_filenames, _mv.format_filetypes, _mv.format_hr_filetypes,
    _mv.format_mediatypes, _mv.format_extents,
]

_OPDS_COLUMNS = [
    _mv.book_id, _mv.title, _mv.downloads,
    cast(_mv.release_date, Text).label("release_date"),
    _mv.copyrighted, _mv.lang_codes,
    _mv.creator_ids, _mv.creator_names, _mv.creator_roles,
    _mv.creator_born_floor, _mv.creator_born_ceil,
    _mv.creator_died_floor, _mv.creator_died_ceil,
    _mv.subject_ids, _mv.subject_names, _mv.bookshelf_ids, _mv.bookshelf_names,
    _mv.locc_codes, _mv.dcmitypes, _mv.publisher, _mv.summary,
    _mv.reading_level, _mv.format_filenames, _mv.format_filetypes,
    _mv.format_hr_filetypes, _mv.format_mediatypes, _mv.format_extents,
]


def _linked(link, fk: str, value, book_id=_mv.book_id):
    """EXISTS a row in link table `link` tying book_id to `value` via `fk`."""
    return exists().where(link.c.fk_books == book_id, link.c[fk] == value)


def _also_downloaded_counts(book_id: int):
    """Subquery d(pk, dl): books co-downloaded with book_id and how often."""
    ad = _also_downloads
    sessions = select(ad.c.id).where(ad.c.fk_books == book_id).subquery("sessions")
    other = _also_downloads.alias("other")
    per_session = (
        select(other.c.fk_books, func.count().label("cnt"))
        .where(other.c.id == sessions.c.id, other.c.fk_books != book_id)
        .group_by(other.c.fk_books)
        .lateral("r")
    )
    return (
        select(per_session.c.fk_books.label("pk"), func.sum(per_session.c.cnt).label("dl"))
        .select_from(sessions.join(per_session, true()))
        .group_by(per_session.c.fk_books)
        .subquery("d")
    )


# =============================================================================
# CatalogQuery
# =============================================================================


class CatalogQuery:
    """Chainable query against mv_books_dc.

    Text search is "hybrid": full-text (websearch_to_tsquery) first, falling
    back to trigram word similarity when the FTS query returns nothing.
    """

    def __init__(self, crosswalk: Crosswalk = Crosswalk.OPDS):
        self._search = []  # type: List[Tuple[str, SearchField]]
        self._filters = []  # type: List
        self._order = OrderBy.DOWNLOADS
        self._sort_dir = None  # type: Optional[SortDirection]
        self._page = 1
        self._page_size = 25
        self._crosswalk = crosswalk
        self._also_downloaded_for = None  # type: Optional[int]

    def __getitem__(self, key: Union[int, Tuple]) -> "CatalogQuery":
        """Set pagination: q[3] for page 3, q[2, 50] for page 2 with 50 results."""
        if isinstance(key, tuple):
            self._page = max(1, int(key[0]))
            self._page_size = max(1, min(100, int(key[1])))
        else:
            self._page = max(1, int(key))
        return self

    def order_by(
        self, order: OrderBy, direction: Optional[SortDirection] = None
    ) -> "CatalogQuery":
        self._order = order
        self._sort_dir = direction
        return self

    def filter(self, clause) -> "CatalogQuery":
        """Add a SQLAlchemy boolean clause over mv_books_dc."""
        self._filters.append(clause)
        return self

    def search(self, txt: str, field: SearchField = SearchField.BOOK) -> "CatalogQuery":
        txt = (txt or "").strip()
        if txt:
            self._search.append((txt, field))
        return self

    def _can_fallback(self) -> bool:
        return bool(self._search)

    # Filters

    def etext(self, nr: int) -> "CatalogQuery":
        return self.filter(_mv.book_id == int(nr))

    def lang(self, code: str) -> "CatalogQuery":
        return self.filter(_mv.lang_codes.contains([code.lower()]))

    def modified_after(self, date: str) -> "CatalogQuery":
        return self.filter(cast(_mv.filemtime, Date) >= cast(str(date), Date))

    def locc(self, code: str) -> "CatalogQuery":
        return self.filter(_linked(_mn_books_loccs, "fk_loccs", str(code).upper()))

    def author_id(self, aid: int) -> "CatalogQuery":
        return self.filter(_linked(_mn_books_authors, "fk_authors", int(aid)))

    def subject_id(self, sid: int) -> "CatalogQuery":
        return self.filter(_linked(_mn_books_subjects, "fk_subjects", int(sid)))

    def bookshelf_id(self, bid: int) -> "CatalogQuery":
        return self.filter(_linked(_mn_books_bookshelves, "fk_bookshelves", int(bid)))

    def also_downloaded(self, book_id: int) -> "CatalogQuery":
        """Books co-downloaded with the given ebook (scores.also_downloads)."""
        self._also_downloaded_for = int(book_id)
        return self

    def where(self, sql: str, **params) -> "CatalogQuery":
        """Add raw SQL filter condition. BE CAREFUL WHEN USING!"""
        return self.filter(text(sql).bindparams(**params))

    # SQL building

    def _search_clauses(self, fuzzy: bool) -> List:
        clauses = []
        for txt, field in self._search:
            fts_col, text_col = _FIELD_COLS[field]
            if fuzzy:
                clauses.append(literal(txt).bool_op("<%")(text_col))
            else:
                clauses.append(
                    fts_col.bool_op("@@")(func.websearch_to_tsquery("english", txt))
                )
        return clauses

    def _order_by(self, fuzzy: bool) -> List:
        if self._order == OrderBy.RELEVANCE and self._search:
            txt, field = self._search[-1]
            fts_col, text_col = _FIELD_COLS[field]
            rank_q = txt.replace("%", "")
            if fuzzy:
                rank = func.word_similarity(rank_q, text_col)
            else:
                rank = func.ts_rank_cd(fts_col, func.websearch_to_tsquery("english", rank_q))
            return [rank.desc(), _mv.downloads.desc()]

        if self._order == OrderBy.RANDOM:
            return [func.random()]

        if self._order not in _ORDER_COLUMNS:
            return [_mv.downloads.desc()]

        col, default_dir, nulls_last = _ORDER_COLUMNS[self._order]
        direction = self._sort_dir or default_dir
        clause = col.desc() if direction == SortDirection.DESC else col.asc()
        return [clause.nulls_last() if nulls_last else clause]

    def _select(self, *cols, fuzzy: bool = False) -> Select:
        """SELECT cols for this query, ordered but not paginated."""
        if self._also_downloaded_for is not None:
            d = _also_downloaded_counts(self._also_downloaded_for)
            return (
                select(*cols)
                .select_from(d.join(mv_books_dc, _mv.book_id == d.c.pk))
                .order_by(d.c.dl.desc())
            )
        return (
            select(*cols)
            .select_from(mv_books_dc)
            .where(*self._search_clauses(fuzzy), *self._filters)
            .order_by(*self._order_by(fuzzy))
        )

    def build(self, *, with_count: bool = False, fuzzy: bool = False) -> Select:
        cols = list(
            _OPDS_SMALL_COLUMNS if self._crosswalk == Crosswalk.OPDS_SMALL else _OPDS_COLUMNS
        )
        if with_count:
            cols.append(func.count().over().label("total_count"))
        return (
            self._select(*cols, fuzzy=fuzzy)
            .limit(self._page_size)
            .offset((self._page - 1) * self._page_size)
        )

    def build_count(self) -> Select:
        return self._select(func.count()).order_by(None)


# =============================================================================
# Catalog
# =============================================================================


class Catalog:
    """Database access for the OPDS feed."""

    def __init__(self, engine):
        self.engine = engine

    def query(self, crosswalk: Crosswalk = Crosswalk.OPDS) -> CatalogQuery:
        return CatalogQuery(crosswalk)

    def execute(self, q: CatalogQuery, with_count: bool = True) -> Dict:
        """Execute query and return paginated results.

        with_count=False skips the window total ('total' comes back None);
        use it for preview feeds that don't paginate.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(q.build(with_count=with_count)).fetchall()
            if q._can_fallback() and not rows:
                rows = conn.execute(
                    q.build(with_count=with_count, fuzzy=True)
                ).fetchall()

        if with_count:
            total = rows[0].total_count if rows else 0
            total_pages = max(1, (total + q._page_size - 1) // q._page_size)
        else:
            total = None
            total_pages = 1

        crosswalk = CROSSWALK_MAP[q._crosswalk]
        return {
            "results": [crosswalk(r) for r in rows],
            "page": q._page,
            "page_size": q._page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def count(self, q: CatalogQuery) -> int:
        """Count results without fetching."""
        with self.engine.connect() as conn:
            return conn.execute(q.build_count()).scalar() or 0

    def curated_shelves(self, cat: CuratedBookshelves) -> List[Tuple[int, str]]:
        """(shelf_id, label) pairs for a curated category."""
        return list(cat.shelves)

    def bookshelf_counts(self, shelf_ids: List[int]) -> Dict[int, int]:
        """Book count per shelf (books present in mv_books_dc), in one query."""
        if not shelf_ids:
            return {}
        mbb = _mn_books_bookshelves
        stmt = (
            select(mbb.c.fk_bookshelves.label("id"), func.count().label("n"))
            .select_from(mbb.join(mv_books_dc, _mv.book_id == mbb.c.fk_books))
            .where(mbb.c.fk_bookshelves.in_(list(shelf_ids)))
            .group_by(mbb.c.fk_bookshelves)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return {r.id: r.n for r in rows}

    def list_subjects(self, limit: Optional[int] = None) -> List[Dict]:
        """Subjects with at least one book, most books first: {'id', 'name', 'book_count'}."""
        s, mbs = _subjects, _mn_books_subjects
        book_count = func.count(mbs.c.fk_books)
        stmt = (
            select(s.c.pk.label("id"), s.c.subject.label("name"), book_count.label("book_count"))
            .select_from(s.join(mbs, s.c.pk == mbs.c.fk_subjects))
            .group_by(s.c.pk, s.c.subject)
            .order_by(book_count.desc(), s.c.subject)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
            return [
                {"id": r.id, "name": r.name, "book_count": r.book_count} for r in rows
            ]

    def get_subject_name(self, subject_id: int) -> Optional[str]:
        stmt = select(_subjects.c.subject).where(_subjects.c.pk == subject_id)
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar()

    def get_facets_for_query(
        self,
        scope_q: CatalogQuery,
        *,
        lang: str = "",
        subject_id: Optional[int] = None,
        subject_limit: Optional[int] = None,
        language_limit: Optional[int] = None,
        include_subjects: bool = True,
        include_languages: bool = True,
    ) -> Dict[str, List[Dict]]:
        """Subject and language facets over scope_q in one round-trip.

        Each facet ignores its own selection: subject counts are narrowed
        by lang, language counts by subject_id.
        """
        if not include_subjects and not include_languages:
            return {"subjects": [], "languages": []}

        scoped = scope_q._select(_mv.book_id, _mv.lang_codes).order_by(None).cte("scoped")
        parts = []

        if include_subjects:
            s, mbs = _subjects, _mn_books_subjects
            subjects = (
                select(
                    literal_column("'subject'").label("facet"),
                    cast(s.c.pk, Text).label("key"),
                    s.c.subject.label("label"),
                    func.count().label("count"),
                )
                .select_from(
                    scoped.join(mbs, mbs.c.fk_books == scoped.c.book_id).join(
                        s, s.c.pk == mbs.c.fk_subjects
                    )
                )
                .group_by(s.c.pk, s.c.subject)
                .order_by(func.count().desc())
            )
            if lang:
                subjects = subjects.where(scoped.c.lang_codes.contains([lang.lower()]))
            if subject_limit is not None:
                subjects = subjects.limit(max(1, int(subject_limit)))
            parts.append(subjects)

        if include_languages:
            langs = select(func.unnest(scoped.c.lang_codes).label("lang"))
            if subject_id is not None:
                langs = langs.where(
                    _linked(_mn_books_subjects, "fk_subjects", int(subject_id),
                            book_id=scoped.c.book_id)
                )
            langs = langs.subquery("langs")
            languages = (
                select(
                    literal_column("'language'").label("facet"),
                    langs.c.lang.label("key"),
                    cast(null(), Text).label("label"),
                    func.count().label("count"),
                )
                .group_by(langs.c.lang)
                .order_by(func.count().desc())
            )
            if language_limit is not None:
                languages = languages.limit(max(1, int(language_limit)))
            parts.append(languages)

        stmt = union_all(*parts) if len(parts) > 1 else parts[0]

        subjects_out = []
        languages_out = []
        with self.engine.connect() as conn:
            for row in conn.execute(stmt).mappings():
                if row["facet"] == "subject":
                    subjects_out.append(
                        {"id": int(row["key"]), "name": row["label"], "count": row["count"]}
                    )
                else:
                    languages_out.append({"code": row["key"], "count": row["count"]})

        return {"subjects": subjects_out, "languages": languages_out}

    def get_opds_facets(
        self,
        scope_fn: Callable[[CatalogQuery], CatalogQuery],
        lang: str = "",
        subject_id: Optional[int] = None,
        *,
        subject_limit: int = 10,
        include_subjects: bool = True,
    ) -> Dict[str, Optional[List[Dict]]]:
        """OPDS facet counts in one query.

        Subjects use scope + lang; languages use scope + subject_id.
        """
        try:
            data = self.get_facets_for_query(
                scope_fn(self.query()),
                lang=lang,
                subject_id=subject_id,
                subject_limit=subject_limit,
                include_subjects=include_subjects,
            )
            subjects = data["subjects"] if include_subjects else None
            if include_subjects and subject_id is not None and subjects is not None:
                if not any(s["id"] == subject_id for s in subjects):
                    name = self.get_subject_name(subject_id)
                    if name:
                        pin_q = scope_fn(self.query())
                        if lang:
                            pin_q.lang(lang)
                        pin_q.subject_id(subject_id)
                        subjects = [
                            {
                                "id": subject_id,
                                "name": name,
                                "count": self.count(pin_q),
                            },
                            *subjects,
                        ][:subject_limit]
            return {
                "subjects": subjects,
                "languages": data["languages"],
            }
        except Exception:
            logging.getLogger(__name__).exception("OPDS facet query failed")
            return {"subjects": None, "languages": None}

    def get_locc_children(self, parent: str = "") -> List[Dict]:
        """Return LoCC children for parent (main classes when parent is empty)."""
        parent_code = (parent or "").strip().upper()
        lc = _loccs
        stmt = select(lc.c.pk.label("code"), lc.c.locc.label("label"))

        if not parent_code:
            stmt = stmt.where(func.char_length(lc.c.pk) == 1).order_by(lc.c.pk)
        elif len(parent_code) == 1:
            stmt = stmt.where(
                lc.c.pk.like(f"{parent_code}%"),
                lc.c.pk != parent_code,
                exists().where(_mn_books_loccs.c.fk_loccs == lc.c.pk),
            ).order_by(func.char_length(lc.c.pk), lc.c.pk)
        else:
            return []

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [{"code": r["code"], "label": r["label"]} for r in rows]
