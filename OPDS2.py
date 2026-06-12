"""
OPDS2.py — Zachary Rosario

OPDS 2.0 JSON feed for the Project Gutenberg catalog.
"""

import datetime
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode
import logging
import json

import cherrypy

from mv_search.constants import (
    Crosswalk,
    CuratedBookshelves,
    Language,
    LoCCMainClass,
    OrderBy,
    SearchType,
    SortDirection,
)
from mv_search.Search import FullTextSearch

SAMPLE_LIMIT = 15
# keep random spotlight picks to reasonably popular books
SPOTLIGHT_MIN_DOWNLOADS = 1000
# locc counts only change on the daily MV refresh, so a long TTL is safe
LOCC_COUNTS_TTL = 6 * 3600
# Most common Gutenberg languages first, remainder alphabetical by label
_LANG_PRIORITY = [
    "en",
    "fr",
    "de",
    "fi",
    "nl",
    "it",
    "pt",
    "es",
    "zh",
    "la",
    "el",
    "grc",
    "hu",
    "sv",
    "da",
    "no",
    "pl",
    "ru",
    "cs",
    "ja",
]
LANGUAGES = [
    {"code": lang.code, "label": lang.label}
    for lang in Language
    if lang.code in _LANG_PRIORITY
]
LANGUAGES.sort(key=lambda x: _LANG_PRIORITY.index(x["code"]))

VALID_SORTS = set(OrderBy._value2member_map_.keys())
OPDS_TYPE = "application/opds+json"


# Helpers
def _json_error_page(status, message, traceback, version):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = OPDS_TYPE
    return json.dumps(
        {
            "metadata": {
                "title": status,
                "description": message,
            },
            "links": [
                _link("self", cherrypy.request.path_info),
                _link("start", "/opds/"),
            ],
            "publications": [],
        }
    )


def _link(rel: str, href: str, **extras) -> Dict:
    """Create an OPDS link dict."""
    return {"rel": rel, "href": href, "type": OPDS_TYPE, **extras}


def _nav(href: str, title: str) -> Dict:
    """Create a navigation item."""
    return {"href": href, "title": title, "type": OPDS_TYPE, "rel": "subsection"}


def _facet(href: str, title: str, active: bool) -> Dict:
    """Create a facet link. Includes 'rel': 'self' only if active."""
    link = {"href": href, "type": OPDS_TYPE, "title": title}
    if active:
        link["rel"] = "self"
    return link


def _url(path: str, params: Dict) -> str:
    """Build URL with query string, omitting empty values."""
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    return f"{path}?{urlencode(clean, doseq=True)}" if clean else path


def _make_page_url(endpoint: str, base: Dict, query: str) -> Callable[[int], str]:
    """Create a page URL builder for pagination links."""

    def page_url(p: int) -> str:
        return _url(endpoint, {**base, "query": query, "page": p})

    return page_url


def _make_facet_url(endpoint: str, base: Dict) -> Callable[..., str]:
    """Create a facet URL builder for filter facets."""

    def facet_url(q: str, lng: str, ab: str, srt: str, so: str) -> str:
        return _url(
            endpoint,
            {
                **base,
                "query": q,
                "page": 1,
                "lang": lng,
                "audiobook": ab,
                "sort": srt,
                "sort_order": so,
            },
        )

    return facet_url


def _paginate(page, limit, default=25) -> Tuple[int, int]:
    """Parse and clamp pagination params."""
    try:
        return max(1, int(page)), max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        return 1, default


def _sort_direction(order: str) -> Optional[SortDirection]:
    """Parse sort order string."""
    return {"asc": SortDirection.ASC, "desc": SortDirection.DESC}.get(order)


# CherryPy Search API
class OPDSFeed:
    def __init__(self):
        self._fts = None
        self._locc_counts_cache = {}  # parent -> (timestamp, counts)

    @property
    def fts(self):
        if self._fts is None:
            self._fts = FullTextSearch(cherrypy.engine.pool.pool)
        return self._fts

    # Query Helpers
    def _filter(self, q, lang: str, audiobook: str):
        """Apply common filters to query."""
        if lang:
            q.lang(lang)
        if audiobook == "true":
            q.audiobook()
        elif audiobook == "false":
            q.text_only()
        return q

    def _sort(self, q, sort: str, sort_order: str):
        """Apply sorting to query."""
        if sort in VALID_SORTS:
            q.order_by(OrderBy(sort), _sort_direction(sort_order))
        else:
            q.order_by(OrderBy.DOWNLOADS)
        return q

    def _top_subjects(self, q) -> Optional[List[Dict]]:
        """Get top subjects for a query."""
        try:
            return self.fts.get_top_subjects_for_query(q, limit=15, max_books=500)
        except Exception as e:
            cherrypy.log(f"Top subjects error: {e}")
            return None

    def _locc_counts(self, parent: str, children: List[Dict]) -> Dict[str, int]:
        """Nav counts for a LoCC page, cached per parent."""
        cached = self._locc_counts_cache.get(parent)
        if cached and time.time() - cached[0] < LOCC_COUNTS_TTL:
            return cached[1]
        try:
            counts = self.fts.get_locc_nav_counts(children)
        except Exception as e:
            cherrypy.log(f"LoCC nav counts error: {e}", severity=logging.WARNING)
            return {}
        self._locc_counts_cache[parent] = (time.time(), counts)
        return counts

    # Feed Building
    def _pagination_links(
        self, url_fn: Callable, page: int, total_pages: int
    ) -> List[Dict]:
        """Build pagination links."""
        links = []
        if page > 1:
            links.append(_link("first", url_fn(1)))
            links.append(_link("previous", url_fn(page - 1)))
        if page < total_pages:
            links.append(_link("next", url_fn(page + 1)))
            links.append(_link("last", url_fn(total_pages)))
        return links

    # Error handling

    def _error_feed(
        self,
        title: str,
        detail: str,
        self_href: str,
        up_href: str = "/opds/",
        status: int = 500,
    ) -> Dict:
        cherrypy.response.status = status
        return {
            "metadata": {
                "title": title,
                "numberOfItems": 0,
                "description": detail,
            },
            "links": [
                _link("self", self_href),
                _link("start", "/opds/"),
                _link("up", up_href),
            ],
            "publications": [],
        }

    def _facets(
        self,
        url_fn: Callable,
        query: str,
        lang: str,
        audiobook: str,
        sort: str,
        sort_order: str,
        subjects: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Build common facets for sort, copyright, format, language."""
        facets = [
            {
                "metadata": {"title": "Sort By"},
                "links": [
                    _facet(
                        url_fn(query, lang, audiobook, "downloads", "desc"),
                        "Most Popular",
                        sort in ("downloads", ""),
                    ),
                    _facet(
                        url_fn(query, lang, audiobook, "relevance", ""),
                        "Relevance",
                        sort == "relevance",
                    ),
                    _facet(
                        url_fn(query, lang, audiobook, "title", "asc"),
                        "Title (A-Z)",
                        sort == "title",
                    ),
                    _facet(
                        url_fn(query, lang, audiobook, "author", "asc"),
                        "Author (A-Z)",
                        sort == "author",
                    ),
                    _facet(
                        url_fn(query, lang, audiobook, "random", ""),
                        "Random",
                        sort == "random",
                    ),
                ],
            }
        ]

        if subjects:
            facets.append(
                {
                    "metadata": {"title": "Top Subjects in Results"},
                    "links": [
                        {
                            "href": f"/opds/subjects?id={s['id']}",
                            "type": OPDS_TYPE,
                            "title": s["name"],
                            "properties": {"numberOfItems": s["count"]},
                        }
                        for s in subjects
                    ],
                }
            )

        facets.extend(
            [
                {
                    "metadata": {"title": "Format"},
                    "links": [
                        _facet(
                            url_fn(query, lang, "", sort, sort_order),
                            "Any",
                            not audiobook,
                        ),
                        _facet(
                            url_fn(query, lang, "false", sort, sort_order),
                            "Text",
                            audiobook == "false",
                        ),
                        _facet(
                            url_fn(query, lang, "true", sort, sort_order),
                            "Audiobook",
                            audiobook == "true",
                        ),
                    ],
                },
                {
                    "metadata": {"title": "Language"},
                    "links": [
                        _facet(
                            url_fn(query, "", audiobook, sort, sort_order),
                            "Any",
                            not lang,
                        )
                    ]
                    + [
                        _facet(
                            url_fn(
                                query,
                                item["code"],
                                audiobook,
                                sort,
                                sort_order,
                            ),
                            item["label"],
                            lang == item["code"],
                        )
                        for item in LANGUAGES
                    ],
                },
            ]
        )
        return facets

    # Index
    @cherrypy.expose
    def index(self):
        """Root catalog."""

        def _recently_added():
            result = self.fts.execute(
                self.fts.query(crosswalk=Crosswalk.OPDS).order_by(
                    OrderBy.RELEASE_DATE, SortDirection.DESC
                )[1, SAMPLE_LIMIT],
                with_count=False,
            )
            if result.get("results"):
                return {
                    "metadata": {
                        "title": "Recently Added",
                        "numberOfItems": len(result["results"]),
                    },
                    "links": [
                        _link("self", "/opds/search?sort=release_date&sort_order=desc")
                    ],
                    "publications": result["results"],
                }

        def _most_popular():
            result = self.fts.execute(
                self.fts.query(crosswalk=Crosswalk.OPDS).order_by(OrderBy.DOWNLOADS)[
                    1, SAMPLE_LIMIT
                ],
                with_count=False,
            )
            if result.get("results"):
                return {
                    "metadata": {
                        "title": "Most Popular",
                        "numberOfItems": len(result["results"]),
                    },
                    "links": [
                        _link("self", "/opds/search?sort=downloads&sort_order=desc")
                    ],
                    "publications": result["results"],
                }

        def _audiobooks():
            result = self.fts.execute(
                self.fts.query(crosswalk=Crosswalk.OPDS)
                .audiobook()
                .order_by(OrderBy.DOWNLOADS)[1, SAMPLE_LIMIT],
                with_count=False,
            )
            if result.get("results"):
                return {
                    "metadata": {
                        "title": "Audiobooks",
                        "numberOfItems": len(result["results"]),
                    },
                    "links": [
                        _link("self", "/opds/search?audiobook=true&sort=downloads")
                    ],
                    "publications": result["results"],
                }

        def _category_group(cat):
            """Daily spotlight shelf, random picks above the downloads floor."""
            shelves = list(cat.shelves)
            day = datetime.date.today().toordinal()

            for offset in range(len(shelves)):
                shelf_id, shelf_name = shelves[(day + offset) % len(shelves)]
                try:
                    result = self.fts.execute(
                        self.fts.query(crosswalk=Crosswalk.OPDS)
                        .bookshelf_id(shelf_id)
                        .downloads_gte(SPOTLIGHT_MIN_DOWNLOADS)
                        .order_by(OrderBy.RANDOM)[1, SAMPLE_LIMIT],
                        with_count=False,
                    )
                    if result.get("results"):
                        return {
                            "metadata": {
                                "title": f"{cat.genre}: {shelf_name}",
                                "numberOfItems": len(result["results"]),
                            },
                            "links": [
                                _link("self", f"/opds/bookshelves?id={shelf_id}")
                            ],
                            "publications": result["results"],
                        }
                except Exception as e:
                    cherrypy.log(
                        f"Index group error ({cat.name}/{shelf_id}): {e}",
                        severity=logging.WARNING,
                    )

        tasks = [_recently_added, _most_popular, _audiobooks] + [
            lambda c=cat: _category_group(c) for cat in CuratedBookshelves
        ]

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(fn) for fn in tasks]
            groups = []
            for f in futures:
                try:
                    result = f.result()
                    if result:
                        groups.append(result)
                except Exception as e:
                    cherrypy.log(f"Index group error: {e}")

        return {
            "metadata": {"title": "Project Gutenberg Catalog"},
            "links": [
                _link("self", "/opds/"),
                _link("start", "/opds/"),
                _link("search", "/opds/search{?query}", templated=True),
            ],
            "navigation": [
                _nav("/opds/loccs", "Browse Subjects"),
            ],
            "groups": groups,
        }

    # Bookshelves
    @cherrypy.expose
    def bookshelves(
        self,
        id: Optional[int] = None,
        category: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
        query: str = "",
        lang: str = "",
        audiobook: str = "",
        sort: str = "",
        sort_order: str = "",
    ):
        """Bookshelf navigation."""
        page, limit = _paginate(page, limit)

        if id is not None:
            return self._bookshelf_books(
                int(id),
                page,
                limit,
                query,
                lang,
                audiobook,
                sort,
                sort_order,
            )
        if category is not None:
            return self._bookshelf_category(category)

        return {
            "metadata": {
                "title": "Bookshelves",
                "numberOfItems": len(CuratedBookshelves),
            },
            "links": [
                _link("self", "/opds/bookshelves"),
                _link("start", "/opds/"),
                _link("up", "/opds/"),
            ],
            "navigation": [
                {
                    **_nav(f"/opds/bookshelves?category={cat.name}", cat.genre),
                    "properties": {"numberOfItems": len(cat.shelves)},
                }
                for cat in CuratedBookshelves
            ],
        }

    def _bookshelf_books(
        self,
        shelf_id: int,
        page: int,
        limit: int,
        query: str,
        lang: str,
        audiobook: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books in a bookshelf."""
        name, parent = f"Bookshelf {shelf_id}", None
        for cat in CuratedBookshelves:
            for sid, sname in cat.shelves:
                if sid == shelf_id:
                    name, parent = sname, cat.name
                    break
            if parent:
                break

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).bookshelf_id(shelf_id)
            self._filter(q, lang, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"Bookshelf error: {e}")
            return self._error_feed(
                "Browse failed",
                "Unable to load bookshelf.",
                f"/opds/bookshelves?id={shelf_id}",
                status=500,
            )

        base = {
            "id": shelf_id,
            "limit": limit,
            "lang": lang,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/bookshelves", base, query)
        facet_url = _make_facet_url("/opds/bookshelves", base)

        subjects_q = self.fts.query().bookshelf_id(shelf_id)
        self._filter(subjects_q, lang, audiobook)

        up = f"/opds/bookshelves?category={parent}" if parent else "/opds/bookshelves"
        feed = {
            "metadata": {
                "title": name,
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", up),
                _link(
                    "search",
                    f"/opds/bookshelves?id={shelf_id}{{&query}}",
                    templated=True,
                ),
            ],
            "publications": result["results"],
            "facets": self._facets(
                facet_url,
                query,
                lang,
                audiobook,
                sort,
                sort_order,
                self._top_subjects(subjects_q),
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    def _bookshelf_category(self, category: str):
        """List shelves in a category with samples."""
        found = next((cat for cat in CuratedBookshelves if cat.name == category), None)
        if not found:
            return self._error_feed(
                "Category not found",
                f"Bookshelf category {category} was not found.",
                f"/opds/bookshelves?category={category}",
                "/opds/bookshelves",
                status=404,
            )

        shelves = [{"id": s[0], "name": s[1]} for s in found.shelves]
        groups = []

        for s in shelves:
            try:
                result = self.fts.execute(
                    self.fts.query(crosswalk=Crosswalk.OPDS)
                    .bookshelf_id(s["id"])
                    .order_by(OrderBy.RANDOM)[1, SAMPLE_LIMIT],
                    with_count=False,
                )
                if result.get("results"):
                    groups.append(
                        {
                            "metadata": {
                                "title": s["name"],
                                "numberOfItems": len(result["results"]),
                            },
                            "links": [_link("self", f"/opds/bookshelves?id={s['id']}")],
                            "publications": result["results"],
                        }
                    )
            except Exception as e:
                cherrypy.log(
                    f"Bookshelf sample error {s['id']}: {e}",
                    context="OPDS",
                    severity=logging.WARNING,
                )

        return {
            "metadata": {"title": found.genre, "numberOfItems": len(shelves)},
            "links": [
                _link("self", f"/opds/bookshelves?category={category}"),
                _link("start", "/opds/"),
                _link("up", "/opds/bookshelves"),
            ],
            "groups": groups,
        }

    # LoCC
    @cherrypy.expose
    def loccs(
        self,
        parent: str = "",
        page: int = 1,
        limit: int = 25,
        query: str = "",
        lang: str = "",
        audiobook: str = "",
        sort: str = "",
        sort_order: str = "",
    ):
        """LoCC hierarchical navigation."""
        parent = (parent or "").strip().upper()
        page, limit = _paginate(page, limit)

        try:
            children = self.fts.get_locc_children(parent)
        except Exception as e:
            cherrypy.log(f"LoCC error: {e}")
            children = []

        if children:
            return self._locc_navigation(parent, children)

        return self._locc_books(
            parent, page, limit, query, lang, audiobook, sort, sort_order
        )

    def _locc_navigation(self, parent: str, children: List):
        """Build LoCC category navigation."""
        children.sort(key=lambda x: (len(x.get("code", "")), x.get("code", "")))

        # Get parent label from LoCCMainClass if it's a top-level code
        page_title = "Browse Subjects"
        if parent:
            for item in LoCCMainClass:
                if item.code == parent:
                    page_title = item.label
                    break
            else:
                page_title = f"Classification: {parent}"

        counts = self._locc_counts(parent, children)

        nav = []
        for child in children:
            code = child["code"]
            label = child.get("label", code)
            label = label.split(":", 1)[1].strip() if ":" in label else label

            nav_item = _nav(f"/opds/loccs?parent={code}", label)
            nav_item["properties"] = {"numberOfItems": counts.get(code, 0)}
            nav.append(nav_item)

        return {
            "metadata": {"title": page_title, "numberOfItems": len(children)},
            "links": [
                _link(
                    "self", f"/opds/loccs?parent={parent}" if parent else "/opds/loccs"
                ),
                _link("start", "/opds/"),
                _link("up", "/opds/loccs" if parent else "/opds/"),
            ],
            "navigation": nav,
        }

    def _locc_books(
        self,
        parent: str,
        page: int,
        limit: int,
        query: str,
        lang: str,
        audiobook: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books in a LoCC leaf."""
        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).locc(parent)
            self._filter(q, lang, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"LoCC browse error: {e}")
            return self._error_feed(
                "Browse failed",
                "Unable to load LoCC leaf.",
                f"/opds/loccs?parent={parent}",
                "/opds/loccs",
                status=500,
            )

        base = {
            "parent": parent,
            "limit": limit,
            "lang": lang,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/loccs", base, query)
        facet_url = _make_facet_url("/opds/loccs", base)

        subjects_q = self.fts.query().locc(parent)
        self._filter(subjects_q, lang, audiobook)

        feed = {
            "metadata": {
                "title": parent,
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/loccs"),
                _link(
                    "search", f"/opds/loccs?parent={parent}{{&query}}", templated=True
                ),
            ],
            "publications": result["results"],
            "facets": self._facets(
                facet_url,
                query,
                lang,
                audiobook,
                sort,
                sort_order,
                self._top_subjects(subjects_q),
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    # Subjects

    @cherrypy.expose
    def subjects(
        self,
        id: Optional[int] = None,
        page: int = 1,
        limit: int = 25,
        query: str = "",
        lang: str = "",
        audiobook: str = "",
        sort: str = "",
        sort_order: str = "",
    ):
        """Subject navigation."""
        page, limit = _paginate(page, limit)

        if id is not None:
            return self._subject_books(
                int(id),
                page,
                limit,
                query,
                lang,
                audiobook,
                sort,
                sort_order,
            )

        subjects = sorted(
            self.fts.list_subjects(), key=lambda x: x["book_count"], reverse=True
        )
        return {
            "metadata": {"title": "Subjects", "numberOfItems": len(subjects)},
            "links": [
                _link("self", "/opds/subjects"),
                _link("start", "/opds/"),
                _link("up", "/opds/"),
            ],
            "navigation": [
                {
                    **_nav(f"/opds/subjects?id={s['id']}", s["name"]),
                    "properties": {"numberOfItems": s["book_count"]},
                }
                for s in subjects[:100]
            ],
        }

    def _subject_books(
        self,
        subject_id: int,
        page: int,
        limit: int,
        query: str,
        lang: str,
        audiobook: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books for a subject."""
        name = self.fts.get_subject_name(subject_id) or f"Subject {subject_id}"

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).subject_id(subject_id)
            self._filter(q, lang, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"Subject error: {e}")
            return self._error_feed(
                "Browse failed",
                "Unable to load subject.",
                f"/opds/subjects?id={subject_id}",
                "/opds/subjects",
                status=500,
            )

        base = {
            "id": subject_id,
            "limit": limit,
            "lang": lang,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/subjects", base, query)
        facet_url = _make_facet_url("/opds/subjects", base)

        feed = {
            "metadata": {
                "title": name,
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/subjects"),
                _link(
                    "search",
                    f"/opds/subjects?id={subject_id}{{&query}}",
                    templated=True,
                ),
            ],
            "publications": result["results"],
            "facets": self._facets(facet_url, query, lang, audiobook, sort, sort_order),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    # Search

    @cherrypy.expose
    def search(
        self,
        query: str = "",
        page: int = 1,
        limit: int = 25,
        lang: str = "",
        audiobook: str = "",
        sort: str = "",
        sort_order: str = "",
        locc: str = "",
        author_id: Optional[int] = None,
    ):
        """Full-text search."""
        page, limit = _paginate(page, limit)

        try:
            has_query = bool(query.strip())

            q = self.fts.query(crosswalk=Crosswalk.OPDS)
            if has_query:
                q.search(query, search_type=SearchType.FUZZY)

            if locc:
                q.locc(locc)
            if author_id is not None:
                q.author_id(int(author_id))

            self._filter(q, lang, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])

            subjects = None
            if has_query or locc or lang or author_id is not None:
                sq = self.fts.query()
                if has_query:
                    sq.search(query, search_type=SearchType.FUZZY)
                if locc:
                    sq.locc(locc)
                if author_id is not None:
                    sq.author_id(int(author_id))
                self._filter(sq, lang, audiobook)
                subjects = self._top_subjects(sq)
        except Exception as e:
            cherrypy.log(f"Search error: {e}")
            return self._error_feed(
                "Search failed",
                "Unable to complete search.",
                "/opds/search",
                "/opds/",
                status=500,
            )

        base = {
            "limit": limit,
            "lang": lang,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
            "locc": locc,
            "author_id": author_id,
        }
        page_url = _make_page_url("/opds/search", base, query)
        facet_url = _make_facet_url("/opds/search", base)

        facets = self._facets(
            facet_url, query, lang, audiobook, sort, sort_order, subjects
        )

        feed = {
            "metadata": {
                "title": "Gutenberg Search Results",
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/"),
                _link("search", "/opds/search{?query}", templated=True),
            ],
            "publications": result["results"],
            "facets": facets,
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed


if __name__ == "__main__":
    import os

    from cherrypy.process import plugins
    from libgutenberg import GutenbergDatabase

    import ConnectionPool  # noqa: F401  registers plugins.ConnectionPool

    _local_conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.conf")
    if os.path.exists(_local_conf):
        cherrypy.config.update(_local_conf)
    cherrypy.config.update(
        {"server.socket_host": "0.0.0.0", "server.socket_port": 8080}
    )

    GutenbergDatabase.options.update(cherrypy.config)
    cherrypy.engine.pool = plugins.ConnectionPool(
        cherrypy.engine,
        params=GutenbergDatabase.get_connection_params(cherrypy.config),
    )
    cherrypy.engine.pool.subscribe()

    @cherrypy.tools.register("before_finalize")
    def cors():
        cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
        cherrypy.response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        cherrypy.response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Accept"
        )
        cherrypy.response.headers["Access-Control-Max-Age"] = "86400"
        if cherrypy.request.method == "OPTIONS":
            cherrypy.response.status = 200
            cherrypy.response.body = b""
            cherrypy.request.handler = None

    cherrypy.tree.mount(
        OPDSFeed(),
        "/opds",
        {
            "/": {
                "tools.cors.on": True,
                "tools.json_out.on": True,
                "request.methods_with_bodies": ("POST", "PUT", "PATCH"),
            }
        },
    )
    try:
        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyboardInterrupt:
        cherrypy.engine.exit()
