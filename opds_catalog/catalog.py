"""
catalog.py — Zachary Rosario

Query builder and database access for the OPDS feed, backed by the
mv_books_dc materialized view.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple, Union

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from .constants import (
    BOOKSHELF_CATEGORY_PREFIX,
    Crosswalk,
    CuratedBookshelves,
    LoCCMainClass,
    OrderBy,
    SearchField,
    SortDirection,
)
from .publications import CROSSWALK_MAP

__all__ = [
    "Catalog",
    "CatalogQuery",
]

# (tsvector expression, plain text expression) per searchable field
_FIELD_COLS = {
    SearchField.BOOK: ("tsvec", "book_text"),
    SearchField.TITLE: ("to_tsvector('english', title)", "title"),
    SearchField.AUTHOR: (
        "to_tsvector('english', array_to_string(creator_names, ' '))",
        "array_to_string(creator_names, ' ')",
    ),
}

_ORDER_COLUMNS = {
    OrderBy.DOWNLOADS: ("downloads", SortDirection.DESC, None),
    OrderBy.TITLE: ("title", SortDirection.ASC, None),
    OrderBy.AUTHOR: ("creator_names[1]", SortDirection.ASC, "LAST"),
    OrderBy.RELEASE_DATE: ("CAST(release_date AS date)", SortDirection.DESC, "LAST"),
    OrderBy.FILEMTIME: ("filemtime", SortDirection.DESC, "LAST"),
    OrderBy.RANDOM: ("RANDOM()", None, None),
}

_SELECT = """book_id, title, downloads, CAST(release_date AS text) AS release_date, copyrighted, lang_codes,
    creator_ids, creator_names, creator_roles,
    creator_born_floor, creator_born_ceil, creator_died_floor, creator_died_ceil,
    subject_ids, subject_names, bookshelf_ids, bookshelf_names,
    locc_codes, dcmitypes, publisher, summary,
    reading_level, format_filenames, format_filetypes,
    format_hr_filetypes, format_mediatypes, format_extents"""

_SELECT_OPDS_SMALL = """book_id, title, lang_codes,
    creator_ids, creator_names, creator_roles,
    format_filenames, format_filetypes, format_hr_filetypes,
    format_mediatypes, format_extents"""


# =============================================================================
# CatalogQuery
# =============================================================================


class CatalogQuery:
    """Chainable query against mv_books_dc.

    Text search is "hybrid": full-text (websearch_to_tsquery) first, falling
    back to trigram word similarity when the FTS query returns nothing.
    """

    def __init__(self, crosswalk: Crosswalk = Crosswalk.OPDS):
        # (sql, params, rank_col, text_col)
        self._search = []  # type: List[Tuple[str, Dict, str, str]]
        self._fuzzy = False
        self._filters = []  # type: List[Tuple[str, Dict]]
        self._order = OrderBy.DOWNLOADS
        self._sort_dir = None  # type: Optional[SortDirection]
        self._page = 1
        self._page_size = 25
        self._crosswalk = crosswalk
        self._param_counter = 0
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

    def _new_param(self, value: object) -> Tuple[str, Dict]:
        pname = f"__p{self._param_counter}"
        self._param_counter += 1
        return pname, {pname: value}

    def filter(self, sql_template: str, *values: object) -> "CatalogQuery":
        """Add a filter; each {} in the template becomes a bound parameter."""
        params = {}  # type: Dict
        placeholders = []  # type: List[str]
        for v in values:
            pname, p = self._new_param(v)
            params.update(p)
            placeholders.append(f":{pname}")
        sql = sql_template.format(*placeholders)
        self._filters.append((sql, params))
        return self

    def search(self, txt: str, field: SearchField = SearchField.BOOK) -> "CatalogQuery":
        txt = (txt or "").strip()
        if not txt:
            return self
        fts_col, text_col = _FIELD_COLS[field]
        pname, p = self._new_param(txt)
        sql = f"{fts_col} @@ websearch_to_tsquery('english', :{pname})"
        self._search.append((sql, p, fts_col, text_col))
        return self

    def _can_fallback(self) -> bool:
        return bool(self._search) and not self._fuzzy

    def _use_fuzzy(self) -> None:
        """Switch search clauses from tsvector to trigram search."""
        self._search = [
            (f":{next(iter(p))} <% {text_col}", p, text_col, text_col)
            for _, p, _, text_col in self._search
        ]
        self._fuzzy = True

    # Filters

    def etext(self, nr: int) -> "CatalogQuery":
        return self.filter("book_id = {}", int(nr))

    def lang(self, code: str) -> "CatalogQuery":
        return self.filter("lang_codes @> ARRAY[CAST({} AS text)]", code.lower())

    def modified_after(self, date: str) -> "CatalogQuery":
        return self.filter("CAST(filemtime AS date) >= CAST({} AS date)", str(date))

    def locc(self, code: Union[LoCCMainClass, str]) -> "CatalogQuery":
        code = code.code if isinstance(code, LoCCMainClass) else str(code).upper()
        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_loccs mbl
                JOIN loccs lc ON lc.pk = mbl.fk_loccs
                WHERE mbl.fk_books = book_id
                  AND lc.pk = {}
            )
            """,
            code,
        )

    def author_id(self, aid: int) -> "CatalogQuery":
        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_authors mba
                WHERE mba.fk_books = book_id
                  AND mba.fk_authors = {}
            )
            """,
            int(aid),
        )

    def subject_id(self, sid: int) -> "CatalogQuery":
        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_subjects mbs
                WHERE mbs.fk_books = book_id
                  AND mbs.fk_subjects = {}
            )
            """,
            int(sid),
        )

    def bookshelf_id(self, bid: int) -> "CatalogQuery":
        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_bookshelves mbb
                WHERE mbb.fk_books = book_id
                  AND mbb.fk_bookshelves = {}
            )
            """,
            int(bid),
        )

    def also_downloaded(self, book_id: int) -> "CatalogQuery":
        """Books co-downloaded with the given ebook (scores.also_downloads)."""
        self._also_downloaded_for = int(book_id)
        return self

    def where(self, sql: str, **params) -> "CatalogQuery":
        """Add raw SQL filter condition. BE CAREFUL WHEN USING!"""
        for k in params.keys():
            if k.startswith("__p"):
                raise ValueError(
                    "Parameter name reserved by search engine: starts with '__p'"
                )
        self._filters.append((sql, params))
        return self

    # SQL building

    def _params(self) -> Dict[str, object]:
        params = {}
        for _, p, _, _ in self._search:
            params.update(p)
        for _, p in self._filters:
            params.update(p)
        return params

    def _order_sql(self, params: Dict) -> str:
        if self._order == OrderBy.RELEVANCE and self._search:
            _, p, col, _ = self._search[-1]
            val = next(iter(p.values())) if p else ""
            params["rank_q"] = str(val).replace("%", "")
            if self._fuzzy:
                return f"word_similarity(:rank_q, {col}) DESC, downloads DESC"
            return f"ts_rank_cd({col}, websearch_to_tsquery('english', :rank_q)) DESC, downloads DESC"

        if self._order == OrderBy.RANDOM:
            return "RANDOM()"

        if self._order not in _ORDER_COLUMNS:
            return "downloads DESC"

        col, default_dir, nulls = _ORDER_COLUMNS[self._order]
        direction = self._sort_dir or default_dir
        clause = f"{col} {direction.value.upper()}"
        if nulls:
            clause += f" NULLS {nulls}"
        return clause

    def _where_parts(self) -> Tuple[Optional[str], Optional[str]]:
        search_sql = " AND ".join(s[0] for s in self._search) if self._search else None
        filter_sql = " AND ".join(f[0] for f in self._filters) if self._filters else None
        return search_sql, filter_sql

    def _where_sql(self, param_prefix: str = "") -> Tuple[str, Dict]:
        """WHERE clause and bind params (for facet CTEs)."""
        params = self._params()
        search_sql, filter_sql = self._where_parts()
        where_parts = [p for p in (search_sql, filter_sql) if p]
        if not where_parts:
            return "", dict(params)

        if param_prefix:
            mapping = {old: f"{param_prefix}{old}" for old in params}
            new_params = {mapping[k]: v for k, v in params.items()}
            remapped_parts = []
            for part in where_parts:
                s = part
                for old in sorted(mapping, key=len, reverse=True):
                    s = s.replace(f":{old}", f":{mapping[old]}")
                remapped_parts.append(s)
            return f"WHERE {' AND '.join(remapped_parts)}", new_params

        return f"WHERE {' AND '.join(where_parts)}", dict(params)

    def _result_select(self) -> str:
        if self._crosswalk == Crosswalk.OPDS_SMALL:
            return _SELECT_OPDS_SMALL
        return _SELECT

    def build(self, *, with_count: bool = False) -> Tuple[str, Dict]:
        params = self._params()
        limit, offset = self._page_size, (self._page - 1) * self._page_size
        total_col = ", COUNT(*) OVER() AS total_count" if with_count else ""
        select_cols = self._result_select()

        if self._also_downloaded_for is not None:
            params["__also_dl_for"] = self._also_downloaded_for
            sql = (
                f"SELECT {select_cols}{total_col} FROM ("
                " SELECT r.fk_books AS pk, sum(r.cnt) AS dl"
                " FROM (SELECT id FROM scores.also_downloads"
                " WHERE fk_books = :__also_dl_for) sessions"
                " CROSS JOIN LATERAL ("
                " SELECT fk_books, count(*)::bigint AS cnt"
                " FROM scores.also_downloads"
                " WHERE id = sessions.id"
                " AND fk_books != :__also_dl_for"
                " GROUP BY fk_books"
                " ) r GROUP BY r.fk_books"
                ") d JOIN mv_books_dc ON book_id = d.pk"
                " ORDER BY d.dl DESC"
                f" LIMIT {limit} OFFSET {offset}"
            )
            return sql, params

        order = self._order_sql(params)
        search_sql, filter_sql = self._where_parts()

        if search_sql and filter_sql:
            # Search first (index scan), then filters over the matched rows.
            sql = (
                f"SELECT {select_cols}{total_col} FROM (SELECT * FROM mv_books_dc WHERE {search_sql}) t "
                f"WHERE {filter_sql} ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        elif search_sql:
            sql = (
                f"SELECT {select_cols}{total_col} FROM mv_books_dc WHERE {search_sql} "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        elif filter_sql:
            sql = (
                f"SELECT {select_cols}{total_col} FROM mv_books_dc WHERE {filter_sql} "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        else:
            sql = (
                f"SELECT {select_cols}{total_col} FROM mv_books_dc "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )

        return sql, params

    def build_count(self) -> Tuple[str, Dict]:
        params = self._params()
        if self._also_downloaded_for is not None:
            params["__also_dl_for"] = self._also_downloaded_for
            return (
                "SELECT COUNT(*) FROM ("
                " SELECT r.fk_books AS pk"
                " FROM (SELECT id FROM scores.also_downloads"
                " WHERE fk_books = :__also_dl_for) sessions"
                " CROSS JOIN LATERAL ("
                " SELECT fk_books"
                " FROM scores.also_downloads"
                " WHERE id = sessions.id"
                " AND fk_books != :__also_dl_for"
                " GROUP BY fk_books"
                " ) r GROUP BY r.fk_books"
                ") d"
            ), params

        search_sql, filter_sql = self._where_parts()

        if search_sql and filter_sql:
            return (
                f"SELECT COUNT(*) FROM (SELECT * FROM mv_books_dc WHERE {search_sql}) t"
                f" WHERE {filter_sql}",
                params,
            )
        elif search_sql:
            return f"SELECT COUNT(*) FROM mv_books_dc WHERE {search_sql}", params
        elif filter_sql:
            return f"SELECT COUNT(*) FROM mv_books_dc WHERE {filter_sql}", params
        return "SELECT COUNT(*) FROM mv_books_dc", params


# =============================================================================
# Catalog
# =============================================================================


class Catalog:
    """Database access for the OPDS feed."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=self.engine)
        self._bookshelf_ids = None

    def query(self, crosswalk: Crosswalk = Crosswalk.OPDS) -> CatalogQuery:
        return CatalogQuery(crosswalk)

    def execute(self, q: CatalogQuery, with_count: bool = True) -> Dict:
        """Execute query and return paginated results.

        with_count=False skips the window total ('total' comes back None);
        use it for preview feeds that don't paginate.
        """
        with self.Session() as session:
            sql, params = q.build(with_count=with_count)
            rows = session.execute(text(sql), params).fetchall()
            if q._can_fallback() and not rows:
                q._use_fuzzy()
                sql, params = q.build(with_count=with_count)
                rows = session.execute(text(sql), params).fetchall()

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
        with self.Session() as session:
            sql, params = q.build_count()
            return session.execute(text(sql), params).scalar() or 0

    def bookshelf_ids(self) -> Dict[str, int]:
        """Map of bookshelf name -> primary key, loaded once and cached."""
        if self._bookshelf_ids is None:
            with self.Session() as session:
                rows = session.execute(
                    text("SELECT pk, bookshelf FROM bookshelves")
                ).fetchall()
            self._bookshelf_ids = {r.bookshelf: r.pk for r in rows}
        return self._bookshelf_ids

    def curated_shelves(self, cat: CuratedBookshelves) -> List[Tuple[int, str]]:
        """Resolve a curated category to (shelf_id, label) pairs.

        Labels missing from the current dataset are skipped.
        """
        ids = self.bookshelf_ids()
        resolved = []
        for label in cat.shelf_names:
            pk = ids.get(BOOKSHELF_CATEGORY_PREFIX + label)
            if pk is not None:
                resolved.append((pk, label))
        return resolved

    def list_subjects(self) -> List[Dict]:
        """All subjects with at least one book: {'id', 'name', 'book_count'}."""
        sql = """
            SELECT
                s.pk AS id,
                s.subject AS name,
                COUNT(mbs.fk_books) AS book_count
            FROM subjects s
            LEFT JOIN mn_books_subjects mbs
                ON s.pk = mbs.fk_subjects
            GROUP BY
                s.pk,
                s.subject
            HAVING
                COUNT(mbs.fk_books) > 0
            ORDER BY
                book_count DESC,
                s.subject
        """
        with self.Session() as session:
            rows = session.execute(text(sql)).fetchall()
            return [
                {"id": r.id, "name": r.name, "book_count": r.book_count} for r in rows
            ]

    def get_subject_name(self, subject_id: int) -> Optional[str]:
        with self.Session() as session:
            return session.execute(
                text("SELECT subject FROM subjects WHERE pk = :id"),
                {"id": subject_id},
            ).scalar()

    def get_facets_for_query(
        self,
        subject_q: CatalogQuery,
        language_q: Optional[CatalogQuery] = None,
        *,
        subject_limit: Optional[int] = None,
        language_limit: Optional[int] = None,
        include_subjects: bool = True,
        include_languages: bool = True,
    ) -> Dict[str, List[Dict]]:
        """Subject and language facets in one round-trip.

        subject_q includes active lang (if any), not subject_id.
        language_q includes subject_id (if any), not lang.
        """
        if not include_subjects and not include_languages:
            return {"subjects": [], "languages": []}

        if language_q is None:
            language_q = subject_q

        sub_where, sub_params = subject_q._where_sql()
        lang_where, lang_params = language_q._where_sql()
        dual_base = sub_where != lang_where or sub_params != lang_params
        if dual_base and include_languages:
            lang_where, lang_params = language_q._where_sql("lq_")

        params = {}
        if include_subjects:
            params.update(sub_params)
        if include_languages:
            params.update(lang_params)
        cte_parts = []
        subject_from = ""
        language_from = ""

        if include_subjects and include_languages and not dual_base:
            cte_parts.append(
                f"""matched_books AS (
                SELECT book_id, lang_codes
                FROM mv_books_dc
                {sub_where}
            )"""
            )
            subject_from = language_from = "matched_books mb"
        else:
            if include_subjects:
                cte_parts.append(
                    f"""subject_books AS (
                    SELECT book_id
                    FROM mv_books_dc
                    {sub_where}
                )"""
                )
                subject_from = "subject_books mb"
            if include_languages:
                cte_parts.append(
                    f"""language_books AS (
                    SELECT book_id, lang_codes
                    FROM mv_books_dc
                    {lang_where}
                )"""
                )
                language_from = "language_books mb"

        subject_limit_clause = ""
        if subject_limit is not None:
            params["subject_limit"] = max(1, int(subject_limit))
            subject_limit_clause = "LIMIT :subject_limit"

        language_limit_clause = ""
        if language_limit is not None:
            params["language_limit"] = max(1, int(language_limit))
            language_limit_clause = "LIMIT :language_limit"

        parts = []
        if include_subjects:
            parts.append(
                f"""(
                SELECT
                    'subject' AS facet,
                    s.pk::text AS key,
                    s.subject AS label,
                    COUNT(*) AS count
                FROM {subject_from}
                JOIN mn_books_subjects mbs
                    ON mbs.fk_books = mb.book_id
                JOIN subjects s
                    ON s.pk = mbs.fk_subjects
                GROUP BY
                    s.pk,
                    s.subject
                ORDER BY
                    count DESC
                {subject_limit_clause}
            )"""
            )
        if include_languages:
            parts.append(
                f"""(
                SELECT
                    'language' AS facet,
                    lang AS key,
                    NULL::text AS label,
                    COUNT(*) AS count
                FROM {language_from},
                    unnest(mb.lang_codes) AS lang
                GROUP BY
                    lang
                ORDER BY
                    count DESC
                {language_limit_clause}
            )"""
            )

        sql = f"""
            WITH {", ".join(cte_parts)}
            {" UNION ALL ".join(parts)}
        """

        subjects = []
        languages = []
        with self.Session() as session:
            for row in session.execute(text(sql), params).fetchall():
                if row.facet == "subject":
                    subjects.append(
                        {"id": int(row.key), "name": row.label, "count": row.count}
                    )
                else:
                    languages.append({"code": row.key, "count": row.count})

        return {"subjects": subjects, "languages": languages}

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
            subject_q = scope_fn(self.query())
            if include_subjects and lang:
                subject_q.lang(lang)
            language_q = scope_fn(self.query())
            if subject_id is not None:
                language_q.subject_id(subject_id)
            data = self.get_facets_for_query(
                subject_q,
                language_q,
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

    def get_locc_children(self, parent: Union[LoCCMainClass, str]) -> List[Dict]:
        """Return LoCC children for parent (main classes when parent is empty)."""
        if isinstance(parent, LoCCMainClass):
            parent_code = parent.code
        else:
            parent_code = (parent or "").strip().upper()

        if not parent_code:
            return [
                {"code": item.code, "label": item.label}
                for item in sorted(LoCCMainClass, key=lambda x: x.code)
            ]

        if len(parent_code) != 1:
            return []

        sql = text(
            """
            SELECT
                lc.pk AS code,
                lc.locc AS label
            FROM loccs lc
            WHERE lc.pk LIKE :pattern
              AND lc.pk != :parent
              AND EXISTS (
                SELECT 1
                FROM mn_books_loccs mbl
                WHERE mbl.fk_loccs = lc.pk
              )
            ORDER BY
                char_length(lc.pk),
                lc.pk
            """
        )

        with self.Session() as session:
            rows = session.execute(
                sql, {"pattern": f"{parent_code}%", "parent": parent_code}
            ).mappings().all()
            return [{"code": r["code"], "label": r["label"]} for r in rows]
