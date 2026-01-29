from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from .constants import (
    Crosswalk,
    Encoding,
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
}
_ORDER_COLUMNS = {
    OrderBy.DOWNLOADS: ("downloads", SortDirection.DESC, None),
    OrderBy.TITLE: ("title", SortDirection.ASC, None),
    OrderBy.AUTHOR: ("creator_names[1]", SortDirection.ASC, "LAST"),
    OrderBy.RELEASE_DATE: ("CAST(release_date AS date)", SortDirection.DESC, "LAST"),
    OrderBy.RANDOM: ("RANDOM()", None, None),
}
_SELECT = (
    "book_id, title, downloads, CAST(release_date AS text) AS release_date, copyrighted, lang_codes, "
    "creator_ids, creator_names, creator_roles, "
    "creator_born_floor, creator_born_ceil, creator_died_floor, creator_died_ceil, "
    "subject_ids, subject_names, bookshelf_ids, bookshelf_names, "
    "locc_codes, is_audio, dcmitypes, publisher, summary, credits, "
    "reading_level, coverpage, format_filenames, format_filetypes, "
    "format_hr_filetypes, format_mediatypes, format_extents"
)
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
        pname = "__p{}".format(self._param_counter)
        self._param_counter += 1
        return pname, {pname: value}

    def filter(self, sql_template: str, *values: object) -> "SearchQuery":
        params = {}  # type: Dict
        placeholders = []  # type: List[str]
        for v in values:
            pname, p = self._new_param(v)
            params.update(p)
            placeholders.append(":{}".format(pname))
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

        if search_type == SearchType.FTS:
            pname, p = self._new_param(txt)
            sql = "{} @@ websearch_to_tsquery('english', :{})".format(fts_col, pname)
            self._search.append((sql, p, fts_col))
        else:
            pname, p = self._new_param(txt)
            self._search.append((":{} <% {}".format(pname, text_col), p, text_col))
        return self

    # Filter Methods

    def etext(self, nr: int) -> "SearchQuery":
        return self.filter("book_id = {}", int(nr))

    def etexts(self, nrs: List[int]) -> "SearchQuery":
        return self.filter("book_id = ANY({})", [int(n) for n in nrs])

    def downloads_gte(self, n: int) -> "SearchQuery":
        return self.filter("downloads >= {}", int(n))

    def downloads_lte(self, n: int) -> "SearchQuery":
        return self.filter("downloads <= {}", int(n))

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
        return self.filter("lang_codes @> ARRAY[CAST({} AS text)]", code_val)

    def text_only(self) -> "SearchQuery":
        self._filters.append(("is_audio = false", {}))
        return self

    def audiobook(self) -> "SearchQuery":
        self._filters.append(("is_audio = true", {}))
        return self

    def author_born_after(self, year: int) -> "SearchQuery":
        return self.filter("max_author_birthyear >= {}", int(year))

    def author_born_before(self, year: int) -> "SearchQuery":
        return self.filter("min_author_birthyear <= {}", int(year))

    def author_died_after(self, year: int) -> "SearchQuery":
        return self.filter("max_author_deathyear >= {}", int(year))

    def author_died_before(self, year: int) -> "SearchQuery":
        return self.filter("min_author_deathyear <= {}", int(year))

    def released_after(self, date: str) -> "SearchQuery":
        return self.filter("CAST(release_date AS date) >= CAST({} AS date)", str(date))

    def released_before(self, date: str) -> "SearchQuery":
        return self.filter("CAST(release_date AS date) <= CAST({} AS date)", str(date))

    def locc(self, code: Union[LoCCMainClass, str]) -> "SearchQuery":
        if isinstance(code, LoCCMainClass):
            code = code.code
        else:
            code = str(code).upper()

        return self.filter(
            "EXISTS (SELECT 1 FROM mn_books_loccs mbl JOIN loccs lc ON lc.pk = mbl.fk_loccs WHERE mbl.fk_books = book_id AND lc.pk LIKE {})",
            "{}%".format(code),
        )

    def contributor_role(self, role: str) -> "SearchQuery":
        return self.filter(
            "EXISTS (SELECT 1 FROM mn_books_authors mba "
            "JOIN roles r ON mba.fk_roles = r.pk "
            "WHERE mba.fk_books = book_id AND r.role = {})",
            role,
        )

    def file_type(self, ft: Union[FileType, str]) -> "SearchQuery":
        if isinstance(ft, FileType):
            ft_value = ft.value
        else:
            ft_value = str(ft)
        return self.filter(
            "EXISTS (SELECT 1 FROM files f "
            "JOIN filetypes ft ON f.fk_filetypes = ft.pk "
            "WHERE f.fk_books = book_id "
            "AND f.obsoleted = 0 AND f.diskstatus = 0 "
            "AND ft.mediatype = {})",
            ft_value,
        )

    def author_id(self, aid: int) -> "SearchQuery":
        return self.filter(
            "EXISTS (SELECT 1 FROM mn_books_authors mba "
            "WHERE mba.fk_books = book_id AND mba.fk_authors = {})",
            int(aid),
        )

    def subject_id(self, sid: int) -> "SearchQuery":
        return self.filter(
            "EXISTS (SELECT 1 FROM mn_books_subjects mbs WHERE mbs.fk_books = book_id AND mbs.fk_subjects = {})",
            int(sid),
        )

    def bookshelf_id(self, bid: int) -> "SearchQuery":
        return self.filter(
            "EXISTS (SELECT 1 FROM mn_books_bookshelves mbb WHERE mbb.fk_books = book_id AND mbb.fk_bookshelves = {})",
            int(bid),
        )

    def encoding(self, enc: Union[Encoding, str]) -> "SearchQuery":
        if isinstance(enc, Encoding):
            enc_val = enc.value
        else:
            enc_val = str(enc)
        return self.filter(
            "EXISTS (SELECT 1 FROM files f "
            "WHERE f.fk_books = book_id "
            "AND f.obsoleted = 0 AND f.diskstatus = 0 "
            "AND f.fk_encodings = {})",
            enc_val,
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
            sql, p, col = self._search[-1]
            val = next(iter(p.values())) if p else ""
            params["rank_q"] = str(val).replace("%", "")
            if "<%" in sql:
                return "word_similarity(:rank_q, {}) DESC, downloads DESC".format(col)
            return "ts_rank_cd({}, websearch_to_tsquery('english', :rank_q)) DESC, downloads DESC".format(col)

        if self._order == OrderBy.RANDOM:
            return "RANDOM()"

        if self._order not in _ORDER_COLUMNS:
            return "downloads DESC"

        col, default_dir, nulls = _ORDER_COLUMNS[self._order]
        direction = self._sort_dir or default_dir
        clause = "{} {}".format(col, direction.value.upper())
        if nulls:
            clause += " NULLS {}".format(nulls)
        return clause

    def build(self) -> Tuple[str, Dict]:
        params = self._params()
        order = self._order_sql(params)
        limit, offset = self._page_size, (self._page - 1) * self._page_size

        search_sql = " AND ".join(s[0] for s in self._search) if self._search else None
        filter_sql = " AND ".join(f[0] for f in self._filters) if self._filters else None

        if search_sql and filter_sql:
            sql = "SELECT {} FROM (SELECT {} FROM mv_books_dc WHERE {}) t WHERE {} ORDER BY {} LIMIT {} OFFSET {}".format(
                _SELECT, _SUBQUERY, search_sql, filter_sql, order, limit, offset
            )
        elif search_sql:
            sql = "SELECT {} FROM mv_books_dc WHERE {} ORDER BY {} LIMIT {} OFFSET {}".format(
                _SELECT, search_sql, order, limit, offset
            )
        elif filter_sql:
            sql = "SELECT {} FROM mv_books_dc WHERE {} ORDER BY {} LIMIT {} OFFSET {}".format(
                _SELECT, filter_sql, order, limit, offset
            )
        else:
            sql = "SELECT {} FROM mv_books_dc ORDER BY {} LIMIT {} OFFSET {}".format(
                _SELECT, order, limit, offset
            )

        return sql, params

    def build_count(self) -> Tuple[str, Dict]:
        params = self._params()
        search_sql = " AND ".join(s[0] for s in self._search) if self._search else None
        filter_sql = " AND ".join(f[0] for f in self._filters) if self._filters else None

        if search_sql and filter_sql:
            return (
                "SELECT COUNT(*) FROM (SELECT {} FROM mv_books_dc WHERE {}) t WHERE {}".format(
                    _SUBQUERY, search_sql, filter_sql
                ),
                params,
            )
        elif search_sql:
            return "SELECT COUNT(*) FROM mv_books_dc WHERE {}".format(search_sql), params
        elif filter_sql:
            return "SELECT COUNT(*) FROM mv_books_dc WHERE {}".format(filter_sql), params
        return "SELECT COUNT(*) FROM mv_books_dc", params


# =============================================================================
# FullTextSearch
# =============================================================================


class FullTextSearch:
    """Main search interface."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=self.engine)

    def query(self, crosswalk: Crosswalk = Crosswalk.PG) -> "SearchQuery":
        """Create a new query builder."""
        q = SearchQuery()
        q._crosswalk = crosswalk
        return q

    def _transform(self, row, cw: Crosswalk) -> Dict:
        return CROSSWALK_MAP[cw](row)

    def execute(self, q: "SearchQuery") -> Dict:
        """Execute query and return paginated results."""
        with self.Session() as session:
            count_sql, count_params = q.build_count()
            total = session.execute(text(count_sql), count_params).scalar() or 0
            total_pages = max(1, (total + q._page_size - 1) // q._page_size)
            q._page = max(1, min(q._page, total_pages))

            sql, params = q.build()
            rows = session.execute(text(sql), params).fetchall()

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

    def list_bookshelves(self) -> List[Dict]:
        """
        List all bookshelves with book counts.

        Returns:
            List of dicts with 'id', 'name', and 'book_count' keys
        """
        sql = """
            SELECT bs.pk AS id, bs.bookshelf AS name, COUNT(mbbs.fk_books) AS book_count
            FROM bookshelves bs
            LEFT JOIN mn_books_bookshelves mbbs ON bs.pk = mbbs.fk_bookshelves
            GROUP BY bs.pk, bs.bookshelf
            ORDER BY bs.bookshelf
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
            SELECT s.pk AS id, s.subject AS name, COUNT(mbs.fk_books) AS book_count
            FROM subjects s
            LEFT JOIN mn_books_subjects mbs ON s.pk = mbs.fk_subjects
            GROUP BY s.pk, s.subject
            ORDER BY book_count DESC, s.subject
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
        sql = "SELECT subject FROM subjects WHERE pk = :id"
        with self.Session() as session:
            result = session.execute(text(sql), {"id": subject_id}).scalar()
            return result

    def get_top_subjects_for_query(
        self, q: "SearchQuery", limit: int = 15, max_books: int = 1000
    ) -> List[Dict]:
        """
        Get top N subjects from a search result set for dynamic facets.

        Args:
            q: SearchQuery to derive subjects from
            limit: Maximum number of subjects to return (default 15)
            max_books: Maximum number of matching books to sample (default 1000)

        Returns:
            List of dicts with 'id', 'name', and 'count' keys, sorted by count desc
        """
        max_books = max(1, min(5000, int(max_books)))
        limit = max(1, min(100, int(limit)))

        params = q._params()
        order_sql = q._order_sql(params)
        search_sql = " AND ".join(s[0] for s in q._search) if q._search else None
        filter_sql = " AND ".join(f[0] for f in q._filters) if q._filters else None
        where_parts = [p for p in (search_sql, filter_sql) if p]
        where_clause = "WHERE {}".format(" AND ".join(where_parts)) if where_parts else ""

        sql = """
            WITH matched_books AS (
                SELECT book_id
                FROM mv_books_dc
                {}
                ORDER BY {}
                LIMIT :max_books
            )
            SELECT
                s.pk AS id,
                s.subject AS name,
                COUNT(*) AS count
            FROM matched_books mb
            JOIN mn_books_subjects mbs ON mbs.fk_books = mb.book_id
            JOIN subjects s ON s.pk = mbs.fk_subjects
            GROUP BY s.pk, s.subject
            ORDER BY count DESC
            LIMIT :limit
        """.format(where_clause, order_sql)
        params["limit"] = limit
        params["max_books"] = max_books

        with self.Session() as session:
            rows = session.execute(text(sql), params).fetchall()
            return [{"id": r.id, "name": r.name, "count": r.count} for r in rows]

    def get_locc_children(self, parent: Union[LoCCMainClass, str]) -> List[Dict]:
        """Get LoCC children for a parent code."""
        if isinstance(parent, LoCCMainClass):
            parent_code = parent.code
        else:
            parent_code = (parent or "").strip().upper()

        if not parent_code:
            sorted_classes = sorted(LoCCMainClass, key=lambda x: x.code)
            return [
                {"code": item.code, "label": item.label, "has_children": True}
                for item in sorted_classes
            ]

        sql = text("""
            SELECT lc.pk AS code, lc.locc AS label,
                EXISTS (
                    SELECT 1 FROM loccs lc2 WHERE lc2.pk LIKE lc.pk || '%' AND lc2.pk != lc.pk
                ) AS has_children
            FROM loccs lc
            WHERE lc.pk LIKE :pattern AND lc.pk != :parent
            ORDER BY char_length(lc.pk), lc.pk
        """)

        with self.Session() as session:
            rows = session.execute(sql, {"pattern": "{}%".format(parent_code), "parent": parent_code}).mappings().all()
            return [
                {"code": r["code"], "label": r["label"], "has_children": bool(r["has_children"])}
                for r in rows
            ]
