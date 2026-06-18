"""
Search.py — Zachary Rosario

Query builder and search interface for the mv_books_dc materialized view.
"""

from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from .constants import (
    BOOKSHELF_CATEGORY_PREFIX,
    Crosswalk,
    CuratedBookshelves,
    FileType,
    Language,
    LoCCMainClass,
    OrderBy,
    SearchField,
    SearchType,
    SortDirection,
)
from .crosswalks import CROSSWALK_MAP

__all__ = [
    "FullTextSearch",
    "SearchQuery",
]

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
    OrderBy.RANDOM: ("RANDOM()", None, None),
}

_SELECT = """book_id, title, downloads, CAST(release_date AS text) AS release_date, copyrighted, lang_codes,
    creator_ids, creator_names, creator_roles,
    creator_born_floor, creator_born_ceil, creator_died_floor, creator_died_ceil,
    subject_ids, subject_names, bookshelf_ids, bookshelf_names,
    locc_codes, is_audio, dcmitypes, publisher, summary, credits,
    reading_level, coverpage, format_filenames, format_filetypes,
    format_hr_filetypes, format_mediatypes, format_extents"""

_SUBQUERY = """book_id, title, downloads, CAST(release_date AS text) AS release_date,
    copyrighted, lang_codes, is_audio,
    creator_ids, creator_names, creator_roles,
    creator_born_floor, creator_born_ceil, creator_died_floor, creator_died_ceil,
    subject_ids, subject_names, bookshelf_ids, bookshelf_names,
    dcmitypes, publisher, summary, credits, reading_level,
    coverpage, format_filenames, format_filetypes, format_hr_filetypes,
    format_mediatypes, format_extents,
    max_author_birthyear, min_author_birthyear,
    max_author_deathyear, min_author_deathyear,
    locc_codes,
    tsvec, book_text"""


# =============================================================================
# SearchQuery
# =============================================================================


class SearchQuery:
    def __init__(self):
        self._search = []  # type: List[Tuple[str, Dict, str]]
        self._filters = []  # type: List[Tuple[str, Dict]]
        self._order = OrderBy.DOWNLOADS
        self._sort_dir = None  # type: Optional[SortDirection]
        self._page = 1
        self._page_size = 25
        self._crosswalk = Crosswalk.PG
        self._param_counter = 0

    def __getitem__(self, key: Union[int, Tuple]) -> "SearchQuery":
        """Set pagination: q[3] for page 3, q[2, 50] for page 2 with 50 results."""
        if isinstance(key, tuple):
            self._page = max(1, int(key[0]))
            self._page_size = max(1, min(100, int(key[1])))
        else:
            self._page = max(1, int(key))
        return self

    def crosswalk(self, cw: Crosswalk) -> "SearchQuery":
        self._crosswalk = cw
        return self

    def order_by(
        self, order: OrderBy, direction: Optional[SortDirection] = None
    ) -> "SearchQuery":
        self._order = order
        self._sort_dir = direction
        return self

    def _new_param(self, value: object) -> Tuple[str, Dict]:
        pname = f"__p{self._param_counter}"
        self._param_counter += 1
        return pname, {pname: value}

    def filter(self, sql_template: str, *values: object) -> "SearchQuery":
        params = {}  # type: Dict
        placeholders = []  # type: List[str]
        for v in values:
            pname, p = self._new_param(v)
            params.update(p)
            placeholders.append(f":{pname}")
        sql = sql_template.format(*placeholders)
        self._filters.append((sql, params))
        return self

    def search(
        self,
        txt: str,
        field: SearchField = SearchField.BOOK,
        search_type: SearchType = SearchType.FTS,
    ) -> "SearchQuery":
        txt = (txt or "").strip()
        if not txt:
            return self

        fts_col, text_col = _FIELD_COLS[field]
        pname, p = self._new_param(txt)

        if search_type == SearchType.FUZZY:
            self._search.append((f":{pname} <% {text_col}", p, text_col))
        elif search_type == SearchType.HYBRID:
            sql = f"{fts_col} @@ websearch_to_tsquery('english', :{pname})"
            self._search.append((sql, p, fts_col, SearchType.HYBRID, text_col))
        else:
            sql = f"{fts_col} @@ websearch_to_tsquery('english', :{pname})"
            self._search.append((sql, p, fts_col))
        return self

    def _is_hybrid(self) -> bool:
        return any(len(s) > 3 and s[3] == SearchType.HYBRID for s in self._search)

    def _use_fuzzy(self) -> None:
        """Switch hybrid clauses from tsvector to trigram search."""
        updated = []
        for s in self._search:
            if len(s) > 3 and s[3] == SearchType.HYBRID:
                _, p, _, _, text_col = s
                pname = next(iter(p))
                updated.append((f":{pname} <% {text_col}", p, text_col))
            else:
                updated.append(s)
        self._search = updated

    # Filter Methods

    def etext(self, nr: int) -> "SearchQuery":
        return self.filter(
            """
            book_id = {}
            """,
            int(nr),
        )

    def etexts(self, nrs: List[int]) -> "SearchQuery":
        return self.filter(
            """
            book_id = ANY({})
            """,
            [int(n) for n in nrs],
        )

    def downloads_gte(self, n: int) -> "SearchQuery":
        return self.filter(
            """
            downloads >= {}
            """,
            int(n),
        )

    def downloads_lte(self, n: int) -> "SearchQuery":
        return self.filter(
            """
            downloads <= {}
            """,
            int(n),
        )

    def public_domain(self) -> "SearchQuery":
        self._filters.append(("copyrighted = 0", {}))
        return self

    def copyrighted(self) -> "SearchQuery":
        self._filters.append(("copyrighted = 1", {}))
        return self

    def lang(self, code: Union[Language, str]) -> "SearchQuery":
        if isinstance(code, Language):
            code_val = code.code
        else:
            code_val = code.lower()
        return self.filter(
            """
            lang_codes @> ARRAY[CAST({} AS text)]
            """,
            code_val,
        )

    def text_only(self) -> "SearchQuery":
        self._filters.append(("is_audio = false", {}))
        return self

    def audiobook(self) -> "SearchQuery":
        self._filters.append(("is_audio = true", {}))
        return self

    def author_born_after(self, year: int) -> "SearchQuery":
        return self.filter(
            """
            max_author_birthyear >= {}
            """,
            int(year),
        )

    def author_born_before(self, year: int) -> "SearchQuery":
        return self.filter(
            """
            min_author_birthyear <= {}
            """,
            int(year),
        )

    def author_died_after(self, year: int) -> "SearchQuery":
        return self.filter(
            """
            max_author_deathyear >= {}
            """,
            int(year),
        )

    def author_died_before(self, year: int) -> "SearchQuery":
        return self.filter(
            """
            min_author_deathyear <= {}
            """,
            int(year),
        )

    def released_after(self, date: str) -> "SearchQuery":
        return self.filter(
            """
            CAST(release_date AS date) >= CAST({} AS date)
            """,
            str(date),
        )

    def released_before(self, date: str) -> "SearchQuery":
        return self.filter(
            """
            CAST(release_date AS date) <= CAST({} AS date)
            """,
            str(date),
        )
        
    def locc(self, code: Union[LoCCMainClass, str]) -> "SearchQuery":
        if isinstance(code, LoCCMainClass):
            code = code.code
        else:
            code = str(code).upper()

        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_loccs mbl
                JOIN loccs lc ON lc.pk = mbl.fk_loccs
                WHERE mbl.fk_books = book_id
                  AND lc.pk LIKE {}
            )
            """,
            f"{code}%",
        )

    def contributor_role(self, role: str) -> "SearchQuery":
        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM mn_books_authors mba
                JOIN roles r ON mba.fk_roles = r.pk
                WHERE mba.fk_books = book_id
                  AND r.role = {}
            )
            """,
            role,
        )

    def file_type(self, ft: Union[FileType, str]) -> "SearchQuery":
        if isinstance(ft, FileType):
            ft_value = ft.value
        else:
            ft_value = str(ft)

        return self.filter(
            """
            EXISTS (
                SELECT 1
                FROM files f
                JOIN filetypes ft ON f.fk_filetypes = ft.pk
                WHERE f.fk_books = book_id
                  AND f.obsoleted = 0
                  AND f.diskstatus = 0
                  AND ft.mediatype = {}
            )
            """,
            ft_value,
        )

    def author_id(self, aid: int) -> "SearchQuery":
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

    def subject_id(self, sid: int) -> "SearchQuery":
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

    def bookshelf_id(self, bid: int) -> "SearchQuery":
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

    def where(self, sql: str, **params) -> "SearchQuery":
        """Add raw SQL filter condition. BE CAREFUL WHEN USING!"""
        for k in params.keys():
            if k.startswith("__p"):
                raise ValueError(
                    "Parameter name reserved by search engine: starts with '__p'"
                )
        self._filters.append((sql, params))
        return self

    # === SQL Building ===

    def _params(self) -> Dict[str, object]:
        params = {}
        for _, p, *_ in self._search:
            params.update(p)
        for _, p in self._filters:
            params.update(p)
        return params

    def _order_sql(self, params: Dict) -> str:
        if self._order == OrderBy.RELEVANCE and self._search:
            sql, p, col = self._search[-1][:3]
            val = next(iter(p.values())) if p else ""
            params["rank_q"] = str(val).replace("%", "")
            if "<%" in sql:
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

    def build(self, *, with_count: bool = False) -> Tuple[str, Dict]:
        params = self._params()
        order = self._order_sql(params)
        limit, offset = self._page_size, (self._page - 1) * self._page_size
        total_col = ", COUNT(*) OVER() AS total_count" if with_count else ""

        search_sql, filter_sql = self._where_parts()

        if search_sql and filter_sql:
            sql = (
                f"SELECT {_SELECT}{total_col} FROM (SELECT {_SUBQUERY} FROM mv_books_dc WHERE {search_sql}) t "
                f"WHERE {filter_sql} ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        elif search_sql:
            sql = (
                f"SELECT {_SELECT}{total_col} FROM mv_books_dc WHERE {search_sql} "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        elif filter_sql:
            sql = (
                f"SELECT {_SELECT}{total_col} FROM mv_books_dc WHERE {filter_sql} "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )
        else:
            sql = (
                f"SELECT {_SELECT}{total_col} FROM mv_books_dc "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            )

        return sql, params

    def build_count(self) -> Tuple[str, Dict]:
        params = self._params()
        search_sql, filter_sql = self._where_parts()

        if search_sql and filter_sql:
            return (
                f"SELECT COUNT(*) FROM (SELECT {_SUBQUERY} FROM mv_books_dc WHERE {search_sql}) t WHERE {filter_sql}",
                params,
            )
        elif search_sql:
            return f"SELECT COUNT(*) FROM mv_books_dc WHERE {search_sql}", params
        elif filter_sql:
            return f"SELECT COUNT(*) FROM mv_books_dc WHERE {filter_sql}", params
        return "SELECT COUNT(*) FROM mv_books_dc", params


# =============================================================================
# FullTextSearch
# =============================================================================


class FullTextSearch:
    """Main search interface."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=self.engine)
        self._bookshelf_ids = None

    def query(self, crosswalk: Crosswalk = Crosswalk.PG) -> "SearchQuery":
        """Create a new query builder."""
        q = SearchQuery()
        q._crosswalk = crosswalk
        return q

    def _transform(self, row, cw: Crosswalk) -> Dict:
        return CROSSWALK_MAP[cw](row)

    def execute(self, q: "SearchQuery", with_count: bool = True) -> Dict:
        """Execute query and return paginated results.

        with_count=False skips the window total ('total' comes back None);
        use it for preview feeds that don't paginate.
        """
        with self.Session() as session:
            sql, params = q.build(with_count=with_count)
            rows = session.execute(text(sql), params).fetchall()
            if q._is_hybrid() and not rows:
                q._use_fuzzy()
                sql, params = q.build(with_count=with_count)
                rows = session.execute(text(sql), params).fetchall()

        if with_count:
            total = rows[0].total_count if rows else 0
            total_pages = max(1, (total + q._page_size - 1) // q._page_size)
        else:
            total = None
            total_pages = 1

        return {
            "results": [self._transform(r, q._crosswalk) for r in rows],
            "page": q._page,
            "page_size": q._page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def count(self, q: "SearchQuery") -> int:
        """Count results without fetching."""
        with self.Session() as session:
            sql, params = q.build_count()
            return session.execute(text(sql), params).scalar() or 0

    def bookshelf_ids(self) -> Dict[str, int]:
        """Map of bookshelf name -> primary key, loaded once and cached.

        Bookshelf rows are static for a given dataset, so curated shelves can
        reference shelves by name and resolve to ids here instead of carrying
        hard-coded primary keys.
        """
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

    def list_bookshelves(self) -> List[Dict]:
        """
        List all bookshelves with book counts.

        Returns:
            List of dicts with 'id', 'name', and 'book_count' keys
        """
        sql = """
            SELECT
                bs.pk AS id,
                bs.bookshelf AS name,
                COUNT(mbbs.fk_books) AS book_count
            FROM bookshelves bs
            LEFT JOIN mn_books_bookshelves mbbs
                ON bs.pk = mbbs.fk_bookshelves
            GROUP BY
                bs.pk,
                bs.bookshelf
            ORDER BY
                bs.bookshelf
        """
        with self.Session() as session:
            rows = session.execute(text(sql)).fetchall()
            return [
                {"id": r.id, "name": r.name, "book_count": r.book_count} for r in rows
            ]

    def list_subjects(self) -> List[Dict]:
        """
        List all subjects with book counts.

        Returns:
            List of dicts with 'id', 'name', and 'book_count' keys
        """
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
        """
        Get a single subject's name by ID (fast lookup).

        Args:
            subject_id: Subject primary key

        Returns:
            Subject name or None if not found
        """
        sql = """
            SELECT
                subject
            FROM subjects
            WHERE pk = :id
        """
        with self.Session() as session:
            result = session.execute(text(sql), {"id": subject_id}).scalar()
            return result

    def get_facets_for_query(
        self,
        q: "SearchQuery",
        *,
        subject_limit: Optional[int] = None,
        language_limit: Optional[int] = None,
        max_books: Optional[int] = None,
        include_subjects: bool = True,
        include_languages: bool = True,
    ) -> Dict[str, List[Dict]]:
        """Subjects and languages from one matched-books scan."""
        if not include_subjects and not include_languages:
            return {"subjects": [], "languages": []}

        params = q._params()
        search_sql, filter_sql = q._where_parts()
        where_parts = [p for p in (search_sql, filter_sql) if p]
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        sample_clause = ""
        if max_books is not None:
            params["max_books"] = max(1, int(max_books))
            sample_clause = f"ORDER BY {q._order_sql(params)} LIMIT :max_books"

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
                f"""
                SELECT
                    'subject' AS facet,
                    s.pk::text AS key,
                    s.subject AS label,
                    COUNT(*) AS count
                FROM matched_books mb
                JOIN mn_books_subjects mbs
                    ON mbs.fk_books = mb.book_id
                JOIN subjects s
                    ON s.pk = mbs.fk_subjects
                GROUP BY
                    s.pk,
                    s.subject
                ORDER BY
                    count DESC
                {subject_limit_clause}"""
            )
        if include_languages:
            parts.append(
                f"""
                SELECT
                    'language' AS facet,
                    lang AS key,
                    NULL::text AS label,
                    COUNT(*) AS count
                FROM matched_books mb,
                    unnest(mb.lang_codes) AS lang
                GROUP BY
                    lang
                ORDER BY
                    count DESC
                {language_limit_clause}"""
            )

        sql = f"""
            WITH matched_books AS (
                SELECT
                    book_id,
                    lang_codes
                FROM mv_books_dc
                {where_clause}
                {sample_clause}
            )
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

    def get_top_subjects_for_query(
        self,
        q: "SearchQuery",
        limit: Optional[int] = None,
        max_books: Optional[int] = None,
    ) -> List[Dict]:
        """Get top subjects from a search result set for dynamic facets."""
        return self.get_facets_for_query(
            q,
            subject_limit=limit,
            max_books=max_books,
            include_subjects=True,
            include_languages=False,
        )["subjects"]

    def get_languages_for_query(
        self,
        q: "SearchQuery",
        limit: Optional[int] = None,
        max_books: Optional[int] = None,
    ) -> List[Dict]:
        """Get languages present in a search result set for dynamic facets."""
        return self.get_facets_for_query(
            q,
            language_limit=limit,
            max_books=max_books,
            include_subjects=False,
            include_languages=True,
        )["languages"]

    def get_locc_children(self, parent: Union[LoCCMainClass, str]) -> List[Dict]:
        """Get LoCC children for a parent code."""
        if isinstance(parent, LoCCMainClass):
            parent_code = parent.code
        else:
            parent_code = (parent or "").strip().upper()

        if not parent_code:
            sorted_classes = sorted(LoCCMainClass, key=lambda x: x.code)
            return [
                {"code": item.code, "label": item.label}
                for item in sorted_classes
            ]

        sql = text(
            """
            SELECT
                lc.pk AS code,
                lc.locc AS label
            FROM loccs lc
            WHERE lc.pk LIKE :pattern
              AND lc.pk != :parent
            ORDER BY
                char_length(lc.pk),
                lc.pk
            """
        )

        with self.Session() as session:
            rows = session.execute(sql, {"pattern": f"{parent_code}%", "parent": parent_code}).mappings().all()
            return [
                {"code": r["code"], "label": r["label"]}
                for r in rows
            ]
