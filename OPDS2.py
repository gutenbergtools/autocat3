"""
OPDS2.py — Zachary Rosario

OPDS 2.0 JSON feed for the Project Gutenberg catalog.
"""

import datetime
import json
import logging
import threading
from functools import partial
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import cherrypy
from repoze.lru import ExpiringLRUCache

from libgutenberg import GutenbergGlobals as gg

from opds_catalog.constants import (
    Crosswalk,
    CuratedBookshelves,
    OrderBy,
    SearchField,
    SortDirection,
)
from opds_catalog.publications import _catalog_url
from opds_catalog.catalog import Catalog

OPDS = Crosswalk.OPDS
OPDS_SMALL = Crosswalk.OPDS_SMALL

SAMPLE_LIMIT = 15
# Most common Gutenberg languages first. Names come from the catalog
# langs table (catalog.langname), same as search, with GutenbergGlobals
# language_map as the fallback.
_LANG_PRIORITY = "en fr de fi nl it pt es zh la el grc hu sv da no pl ru cs ja".split()
_language_map = gg.language_map()


def _language_label(code: str) -> str:
    """Language name from the catalog langs table, else language_map."""
    try:
        from catalog import langname

        label = langname(code)
    except Exception:
        label = ""
    if label and label != "Not a valid language":
        return label
    return _language_map.get(code, code) or code


VALID_SORTS = {o.value for o in OrderBy}
OPDS_TYPE = "application/opds+json"
OPDS_PUBLICATION_TYPE = "application/opds-publication+json"
# Only the user-facing search fields are advertised to clients. /opds/search
# also accepts lang, sort, sort_order, locc, author_id, subject_id,
# bookshelf_id, and modified_since for internal/secret facet/scope carry-over, but those
# are kept out of the template so clients don't surface them as search inputs.
SEARCH_TEMPLATE = "/opds/search{?query,title,author}"

# (sort, sort_order, title) for the "Sort By" facet, in display order.
_SORT_FACETS = (
    ("downloads", "desc", "Most Popular"),
    ("release_date", "desc", "Newest"),
    ("relevance", "", "Relevance"),  # only offered for text searches
    ("title", "asc", "Title (A-Z)"),
    ("author", "asc", "Author (A-Z)"),
    ("random", "", "Random"),
)


# Helpers
def _url(path: str, params: Optional[Dict] = None) -> str:
    """Build an absolute catalog URL, optionally with query params."""
    if params:
        clean = {k: v for k, v in params.items() if v not in ("", None)}
        if clean:
            path = f"{path}?{urlencode(clean, doseq=True)}"
    return _catalog_url(path)


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
    return {"rel": rel, "href": _url(href), "type": OPDS_TYPE, **extras}


def _feed_links(self_href: str, up_href: str, search: bool = True) -> List[Dict]:
    """self/start/up (and search) links shared by every non-root feed."""
    links = [_link("self", self_href), _link("start", "/opds/"), _link("up", up_href)]
    if search:
        links.append(_link("search", SEARCH_TEMPLATE, templated=True))
    return links


OPDS_GZIP_MIME_TYPES = [
    "application/json",
    "application/opds+json",
    "application/opds-publication+json",
]

# Path config for the main app (merge as-is).
OPDS_MOUNT_CONFIG = {
    "/opds": {
        "tools.response_headers.on": True,
        "tools.json_in.on": True,
        "tools.json_out.on": True,
        "tools.gzip.on": True,
        "tools.gzip.mime_types": OPDS_GZIP_MIME_TYPES,
        "tools.I18nTool.on": False,
        "tools.sessions.on": False,
        "error_page.404": _json_error_page,
        "error_page.500": _json_error_page,
        "error_page.default": _json_error_page,
        "tools.response_headers.headers": [
            ("Content-Type", OPDS_TYPE),
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET"),
            ("Access-Control-Allow-Headers", "Accept, Content-Type"),
        ],
    }
}


def _nav(href: str, title: str, count: Optional[int] = None) -> Dict:
    """Create a navigation item, with an item count when given."""
    item = {"href": _url(href), "title": title, "type": OPDS_TYPE, "rel": "subsection"}
    if count:
        item["properties"] = {"numberOfItems": count}
    return item


def _navigation_group() -> Dict:
    """Homepage browse entry points."""
    return {
        "metadata": {"title": "Navigation", "numberOfItems": 2},
        "navigation": [
            _nav("/opds/bookshelves", "Browse Bookshelves"),
            _nav("/opds/loccs", "Browse Subjects"),
        ],
    }


def _facet(href: str, title: str, active: bool, count: Optional[int] = None) -> Dict:
    """Create a facet link. Includes 'rel': 'self' only if active."""
    link = {"href": _url(href), "type": OPDS_TYPE, "title": title}
    if active:
        link["rel"] = "self"
    if count is not None:
        link["properties"] = {"numberOfItems": count}
    return link


def _make_facet_url(endpoint: str, base: Dict) -> Callable[..., str]:
    """Create a facet URL builder for filter facets."""

    def facet_url(q: str, lng: str, srt: str, so: str) -> str:
        return _url(
            endpoint,
            {**base, "query": q, "page": 1, "lang": lng, "sort": srt, "sort_order": so},
        )

    return facet_url


def _paginate(page, limit, default=25) -> Tuple[int, int]:
    """Parse and clamp pagination params."""
    try:
        return max(1, int(page)), max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        return 1, default


def _optional_int(value) -> Optional[int]:
    """Parse CherryPy query params that may arrive as str, int, or empty."""
    if value in (None, ""):
        return None
    return int(value)


def _search_scope(
    q,
    query: str,
    title: str,
    author: str,
    locc: str,
    author_id: Optional[int],
    bookshelf_id: Optional[int],
):
    """Apply search-route filters (not lang or subject_id)."""
    if query.strip():
        q.search(query)
    if title.strip():
        q.search(title, field=SearchField.TITLE)
    if author.strip():
        q.search(author, field=SearchField.AUTHOR)
    if locc:
        q.locc(locc)
    if author_id is not None:
        q.author_id(author_id)
    if bookshelf_id is not None:
        q.bookshelf_id(bookshelf_id)
    return q


def _sort_direction(order: str) -> Optional[SortDirection]:
    """Parse sort order string."""
    return {"asc": SortDirection.ASC, "desc": SortDirection.DESC}.get(order)


def _rotated(items: List) -> List:
    """items rotated by the day number, so spotlights change once per day."""
    k = datetime.date.today().toordinal() % len(items) if items else 0
    return items[k:] + items[:k]


def _book_id(pub: Dict) -> Optional[int]:
    """Extract the numeric Gutenberg id from an OPDS publication."""
    try:
        ident = pub["metadata"]["identifier"]
        if isinstance(ident, str) and "/ebooks/" in ident:
            return int(ident.rstrip("/").rsplit("/", 1)[-1])
    except (KeyError, ValueError, AttributeError, TypeError):
        pass
    return None


def _mark_seen(seen: set, pubs: List[Dict]) -> None:
    """Record publication ids so later samples skip them."""
    seen.update(bid for bid in map(_book_id, pubs) if bid is not None)


# CherryPy Search API
class OPDSFeed:
    """OPDS 2 feed. List/catalog endpoints use OPDS_SMALL; only publications()
    uses OPDS for full book detail."""

    _CACHE_TTL = datetime.timedelta(hours=12)

    def __init__(self):
        self._catalog = None
        self._feed_cache = ExpiringLRUCache(
            256, default_timeout=self._CACHE_TTL.total_seconds()
        )
        # Serializes cache misses so concurrent requests for a cold key
        # don't all run the same (slow) build at once.
        self._cache_lock = threading.Lock()

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = Catalog(cherrypy.engine.pool.engine)
        return self._catalog

    # Query Helpers
    def _query(self, crosswalk=OPDS):
        """Create a catalog query (audiobooks are already excluded by mv_books_dc)."""
        return self.catalog.query(crosswalk)

    def _sort(self, q, sort: str, sort_order: str):
        """Apply sorting to query."""
        if sort in VALID_SORTS:
            q.order_by(OrderBy(sort), _sort_direction(sort_order))
        else:
            q.order_by(OrderBy.DOWNLOADS)
        return q

    def _cache_feed(self, key: str, build: Callable[[], Dict], *, required: str) -> Dict:
        """Return a cached feed with a 12-hour TTL. First request builds it.

        Only feeds with a non-empty `required` section are cached.
        """
        feed = self._feed_cache.get(key)
        if feed is not None:
            return feed
        with self._cache_lock:
            # Re-check: another thread may have built it while we waited.
            feed = self._feed_cache.get(key)
            if feed is None:
                feed = build()
                if feed.get(required):
                    self._feed_cache.put(key, feed)
            return feed

    def _shelf_sample(self, shelf_id: int, seen: set, with_count: bool) -> Dict:
        """Top-downloaded sample for a shelf, excluding already-shown books."""
        q = self._query(OPDS_SMALL).bookshelf_id(shelf_id)
        if seen:
            q.where("book_id <> ALL(:seen_ids)", seen_ids=list(seen))
        result = self.catalog.execute(
            q.order_by(OrderBy.DOWNLOADS)[1, SAMPLE_LIMIT], with_count=with_count
        )
        _mark_seen(seen, result.get("results", []))
        return result

    def _category_count(self, cat) -> int:
        """Count distinct books across all of a category's sub-shelves."""
        try:
            q = self._query().where(
                "EXISTS (SELECT 1 FROM mn_books_bookshelves mbb "
                "WHERE mbb.fk_books = book_id "
                "AND mbb.fk_bookshelves = ANY(:shelf_ids))",
                shelf_ids=[sid for sid, _ in self.catalog.curated_shelves(cat)],
            )
            return self.catalog.count(q)
        except Exception:
            return 0

    def _locc_nav_item_count(self, code: str) -> Optional[int]:
        """Sub-subject count when a code has children; book count at leaves."""
        try:
            sub = self.catalog.get_locc_children(code)
            if sub:
                return len(sub)
            return self.catalog.count(self._query().locc(code))
        except Exception as e:
            cherrypy.log(
                f"LoCC nav count error ({code}): {e}", severity=logging.WARNING
            )
            return None

    # Feed Building
    def _results_feed(
        self,
        endpoint: str,
        base: Dict,
        result: Dict,
        up_href: str,
        *,
        title: str = "Project Gutenberg",
        query: str = "",
        facets: Optional[List[Dict]] = None,
        search_link: bool = True,
    ) -> Dict:
        """Paginated publications feed with self/up/pagination links."""

        def page_url(p: int) -> str:
            return _url(endpoint, {**base, "query": query, "page": p})

        page, total_pages = result["page"], result["total_pages"]
        links = _feed_links(page_url(page), up_href, search=search_link)
        if page > 1:
            links += [_link("first", page_url(1)), _link("previous", page_url(page - 1))]
        if page < total_pages:
            links += [_link("next", page_url(page + 1)), _link("last", page_url(total_pages))]

        feed = {
            "metadata": {
                "title": title,
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": page,
            },
            "links": links,
            "publications": result["results"],
        }
        if facets is not None:
            feed["facets"] = facets
        return feed

    def _browse(
        self,
        endpoint: str,
        key: Dict,
        scope: Callable,
        up_href: str,
        what: str,
        *,
        page: int,
        limit: int,
        lang: str,
        sort: str,
        sort_order: str,
        facet_scope: Optional[Dict] = None,
        include_subjects: bool = True,
    ) -> Dict:
        """Books feed for one bookshelf / LoCC leaf / subject, with facets.

        key is the endpoint's identifying param (e.g. {"id": 68}); scope
        applies the matching filter to a catalog query.
        """
        try:
            q = scope(self._query(OPDS_SMALL))
            if lang:
                q.lang(lang)
            self._sort(q, sort, sort_order)
            result = self.catalog.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"Browse error ({what}): {e}")
            return self._error_feed(
                "Browse failed", f"Unable to load {what}.", _url(endpoint, key), up_href
            )

        base = {**key, "limit": limit, "lang": lang, "sort": sort, "sort_order": sort_order}
        facet_counts = self.catalog.get_opds_facets(
            scope, lang=lang, include_subjects=include_subjects
        )
        facets = self._facets(
            _make_facet_url(endpoint, base),
            "",
            lang,
            sort,
            sort_order,
            facet_counts["subjects"],
            facet_counts["languages"],
            facet_scope,
        )
        return self._results_feed(endpoint, base, result, up_href, facets=facets)

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
            "links": _feed_links(self_href, up_href, search=False),
            "publications": [],
        }

    def _category_not_found(self, category: str, self_href: str, up_href: str) -> Dict:
        return self._error_feed(
            "Category not found",
            f"Bookshelf category {category} was not found.",
            self_href,
            up_href,
            status=404,
        )

    def _facets(
        self,
        url_fn: Callable,
        query: str,
        lang: str,
        sort: str,
        sort_order: str,
        subjects: Optional[List[Dict]] = None,
        languages: Optional[List[Dict]] = None,
        scope: Optional[Dict] = None,
        subject_id: Optional[int] = None,
    ) -> List[Dict]:
        """Build common facets for sort and language.

        languages, when provided, drives a dynamic language facet (codes +
        counts from the result set); otherwise a static common-language list
        is used.

        scope carries the current browse filters (e.g. bookshelf_id, locc) so
        that clicking a Top Subject narrows within that scope instead of
        dropping it.
        """
        sort_links = [
            _facet(
                url_fn(query, lang, key, order),
                title,
                sort == key or (key == "downloads" and not sort),
            )
            for key, order, title in _SORT_FACETS
            if key != "relevance" or query
        ]
        facets = [{"metadata": {"title": "Sort By"}, "links": sort_links}]

        if subjects:
            facets.append(
                {
                    "metadata": {"title": "Top Subjects in Results"},
                    "links": self._subject_links(
                        scope, lang, sort, sort_order, subjects, subject_id
                    ),
                }
            )

        facets.append(
            {
                "metadata": {"title": "Language"},
                "links": self._language_links(
                    url_fn, query, lang, sort, sort_order, languages
                ),
            }
        )
        return facets

    def _language_links(
        self,
        url_fn: Callable,
        query: str,
        lang: str,
        sort: str,
        sort_order: str,
        languages: Optional[List[Dict]],
    ) -> List[Dict]:
        """Language facet links. Dynamic (with counts) when `languages` is
        given, else the static common-language list."""
        if languages is None:
            languages = [{"code": code} for code in _LANG_PRIORITY]
        return [_facet(url_fn(query, "", sort, sort_order), "Any", not lang)] + [
            _facet(
                url_fn(query, item["code"], sort, sort_order),
                _language_label(item["code"]),
                lang == item["code"],
                item.get("count"),
            )
            for item in languages
        ]

    def _subject_links(
        self,
        scope: Optional[Dict],
        lang: str,
        sort: str,
        sort_order: str,
        subjects: List[Dict],
        subject_id: Optional[int],
    ) -> List[Dict]:
        """Subject facet links for search (dynamic counts, Any to clear)."""

        def subject_url(**extra) -> str:
            return _url(
                "/opds/search",
                {
                    **(scope or {}),
                    "lang": lang,
                    "sort": sort,
                    "sort_order": sort_order,
                    **extra,
                },
            )

        return [_facet(subject_url(), "Any", subject_id is None)] + [
            _facet(
                subject_url(subject_id=s["id"]),
                s["name"],
                subject_id == s["id"],
                s["count"],
            )
            for s in subjects
        ]

    # Index
    @cherrypy.expose
    def index(self, **_):
        """Root catalog."""
        return self._cache_feed("index", self._build_index, required="groups")

    def _build_index(self):
        seen = set()

        def _top_group(title: str, order: OrderBy):
            result = self.catalog.execute(
                self._query(OPDS_SMALL).order_by(order, SortDirection.DESC)[
                    1, SAMPLE_LIMIT
                ],
            )
            if result.get("results"):
                _mark_seen(seen, result["results"])
                return {
                    "metadata": {"title": title, "numberOfItems": result["total"]},
                    "links": [
                        _link("self", f"/opds/search?sort={order.value}&sort_order=desc")
                    ],
                    "publications": result["results"],
                }

        def _category_group(cat):
            """Daily spotlight shelf (rotates by date), top picks, deduped."""
            for shelf_id, _shelf_name in _rotated(self.catalog.curated_shelves(cat)):
                try:
                    result = self._shelf_sample(shelf_id, seen, with_count=False)
                    if result.get("results"):
                        return {
                            "metadata": {
                                "title": cat.genre,
                                "numberOfItems": self._category_count(cat),
                            },
                            "links": [
                                _link(
                                    "self",
                                    f"/opds/bookshelf_groups?category={cat.name}",
                                )
                            ],
                            "publications": result["results"],
                        }
                except Exception as e:
                    cherrypy.log(
                        f"Index group error ({cat.name}/{shelf_id}): {e}",
                        severity=logging.WARNING,
                    )

        groups = [_navigation_group()]
        for build in (
            partial(_top_group, "Recently Added", OrderBy.RELEASE_DATE),
            partial(_top_group, "Most Popular", OrderBy.DOWNLOADS),
            *(partial(_category_group, cat) for cat in CuratedBookshelves),
        ):
            try:
                group = build()
                if group:
                    groups.append(group)
            except Exception as e:
                cherrypy.log(f"Index group error: {e}")

        return {
            "metadata": {"title": "Project Gutenberg"},
            "links": [
                _link("self", "/opds/"),
                _link("start", "/opds/"),
                _link("search", SEARCH_TEMPLATE, templated=True),
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
        lang: str = "",
        sort: str = "",
        sort_order: str = "",
        **_,
    ):
        """Bookshelf navigation."""
        page, limit = _paginate(page, limit)

        if id is not None:
            shelf_id = int(id)
            parent = next(
                (cat.name for cat in CuratedBookshelves if shelf_id in dict(cat.shelves)),
                None,
            )
            return self._browse(
                "/opds/bookshelves",
                {"id": shelf_id},
                lambda q: q.bookshelf_id(shelf_id),
                f"/opds/bookshelves?category={parent}" if parent else "/opds/bookshelves",
                "bookshelf",
                facet_scope={"bookshelf_id": shelf_id},
                page=page, limit=limit, lang=lang, sort=sort, sort_order=sort_order,
            )

        if category is not None:
            cat = CuratedBookshelves.__members__.get(category)
            if not cat:
                return self._category_not_found(
                    category, f"/opds/bookshelves?category={category}", "/opds/bookshelves"
                )
            return self._cache_feed(
                f"bookshelf_nav:{category}",
                partial(self._build_bookshelf_category_navigation, cat),
                required="navigation",
            )

        return self._cache_feed(
            "bookshelf_nav:_root", self._build_bookshelf_navigation, required="navigation"
        )

    def _build_bookshelf_navigation(self) -> Dict:
        """Build curated bookshelf category navigation."""
        return {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": len(CuratedBookshelves),
            },
            "links": _feed_links("/opds/bookshelves", "/opds/"),
            "navigation": [
                _nav(f"/opds/bookshelves?category={cat.name}", cat.genre, len(cat.shelf_names))
                for cat in CuratedBookshelves
            ],
        }

    def _build_bookshelf_category_navigation(self, cat: CuratedBookshelves) -> Dict:
        """Build sub-shelf navigation for a curated category."""
        shelves = self.catalog.curated_shelves(cat)
        try:
            counts = self.catalog.bookshelf_counts([sid for sid, _ in shelves])
        except Exception as e:
            cherrypy.log(f"Bookshelf nav count error: {e}", severity=logging.WARNING)
            counts = {}
        nav = [
            _nav(f"/opds/bookshelves?id={sid}", sname, counts.get(sid))
            for sid, sname in shelves
        ]
        return {
            "metadata": {"title": "Project Gutenberg", "numberOfItems": len(nav)},
            "links": _feed_links(f"/opds/bookshelves?category={cat.name}", "/opds/bookshelves"),
            "navigation": nav,
        }

    @cherrypy.expose
    def bookshelf_groups(self, category: Optional[str] = None, **_):
        """Homepage-style category browse with per-shelf preview groups."""
        if category is None:
            return self._error_feed(
                "Category required",
                "A bookshelf category is required.",
                "/opds/bookshelf_groups",
                "/opds/",
                status=400,
            )
        cat = CuratedBookshelves.__members__.get(category)
        if not cat:
            return self._category_not_found(
                category, f"/opds/bookshelf_groups?category={category}", "/opds/"
            )
        return self._cache_feed(
            f"cat:{category}", partial(self._build_bookshelf_groups, cat), required="groups"
        )

    def _build_bookshelf_groups(self, cat: CuratedBookshelves) -> Dict:
        """List shelves in a category with daily spotlight samples."""
        seen = set()
        shelves = self.catalog.curated_shelves(cat)
        # One grouped count for all shelves instead of a COUNT(*) OVER()
        # window in each sample query (which forced a full scan per shelf).
        counts = self.catalog.bookshelf_counts([sid for sid, _ in shelves])
        groups = []
        for sid, sname in _rotated(shelves):
            try:
                result = self._shelf_sample(sid, seen, with_count=False)
                if result.get("results"):
                    groups.append(
                        {
                            "metadata": {"title": sname, "numberOfItems": counts.get(sid, 0)},
                            "links": [_link("self", f"/opds/bookshelves?id={sid}")],
                            "publications": result["results"],
                        }
                    )
            except Exception as e:
                cherrypy.log(
                    f"Bookshelf sample error {sid}: {e}",
                    context="OPDS",
                    severity=logging.WARNING,
                )

        return {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": len(cat.shelf_names),
            },
            "links": _feed_links(f"/opds/bookshelf_groups?category={cat.name}", "/opds/"),
            "groups": groups,
        }

    # LoCC
    @cherrypy.expose
    def loccs(
        self,
        parent: str = "",
        page: int = 1,
        limit: int = 25,
        lang: str = "",
        sort: str = "",
        sort_order: str = "",
        **_,
    ):
        """LoCC hierarchical navigation."""
        parent = (parent or "").strip().upper()
        page, limit = _paginate(page, limit)

        try:
            children = self.catalog.get_locc_children(parent)
        except Exception as e:
            cherrypy.log(f"LoCC error: {e}")
            children = []

        if children:
            return self._cache_feed(
                f"locc_nav:{parent or '_root'}",
                partial(self._build_locc_navigation, parent, children),
                required="navigation",
            )

        return self._browse(
            "/opds/loccs",
            {"parent": parent},
            lambda q: q.locc(parent),
            "/opds/loccs",
            "LoCC leaf",
            facet_scope={"locc": parent},
            page=page, limit=limit, lang=lang, sort=sort, sort_order=sort_order,
        )

    def _build_locc_navigation(self, parent: str, children: List) -> Dict:
        """Build LoCC category navigation (children arrive sorted by code)."""
        nav = []
        for child in children:
            code = child["code"]
            label = child.get("label") or code
            if parent:
                _, sep, rest = label.partition(":")
                if sep:
                    label = rest.strip()
            count = self._locc_nav_item_count(code)
            if count:
                nav.append(_nav(f"/opds/loccs?parent={code}", label, count))

        return {
            "metadata": {"title": "Project Gutenberg", "numberOfItems": len(nav)},
            "links": _feed_links(
                f"/opds/loccs?parent={parent}" if parent else "/opds/loccs",
                "/opds/loccs" if parent else "/opds/",
            ),
            "navigation": nav,
        }

    # Subjects

    def _build_subjects_index(self) -> Dict:
        subjects = self.catalog.list_subjects(limit=100)
        return {
            "metadata": {"title": "Project Gutenberg", "numberOfItems": len(subjects)},
            "links": _feed_links("/opds/subjects", "/opds/"),
            "navigation": [
                _nav(f"/opds/subjects?id={s['id']}", s["name"], s["book_count"])
                for s in subjects
            ],
        }

    @cherrypy.expose
    def subjects(
        self,
        id: Optional[int] = None,
        page: int = 1,
        limit: int = 25,
        lang: str = "",
        sort: str = "",
        sort_order: str = "",
        **_,
    ):
        """Subject navigation."""
        page, limit = _paginate(page, limit)

        if id is None:
            return self._build_subjects_index()

        subject_id = int(id)
        return self._browse(
            "/opds/subjects",
            {"id": subject_id},
            lambda q: q.subject_id(subject_id),
            "/opds/subjects",
            "subject",
            include_subjects=False,
            page=page, limit=limit, lang=lang, sort=sort, sort_order=sort_order,
        )

    # Also downloaded

    @cherrypy.expose
    def also(self, id: int, page: int = 1, limit: int = 25, **_):
        """Books co-downloaded with a given ebook."""
        page, limit = _paginate(page, limit)
        try:
            result = self.catalog.execute(
                self._query(OPDS_SMALL).also_downloaded(int(id))[page, limit]
            )
        except Exception as e:
            cherrypy.log(f"Also downloaded error: {e}")
            return self._error_feed(
                "Browse failed",
                "Unable to load also-downloaded books.",
                f"/opds/also?id={id}",
                f"/opds/publications?id={id}",
                status=500,
            )

        return self._results_feed(
            "/opds/also",
            {"id": id, "limit": limit},
            result,
            f"/opds/publications?id={id}",
            title="Readers also downloaded",
            search_link=False,
        )

    # Publications

    @cherrypy.expose
    def publications(self, id: int, **_):
        """Single publication by Gutenberg ebook number."""
        try:
            result = self.catalog.execute(
                self._query(OPDS).etext(int(id))[1, 1]
            )
        except Exception as e:
            cherrypy.log(f"Publication error: {e}")
            raise cherrypy.HTTPError(500, "Unable to load publication.")

        if not result.get("results"):
            raise cherrypy.HTTPError(404, "No ebook by that number.")

        cherrypy.response.headers["Content-Type"] = OPDS_PUBLICATION_TYPE
        return result["results"][0]

    # Search

    @cherrypy.expose
    def search(
        self,
        query: str = "",
        title: str = "",
        author: str = "",
        page: int = 1,
        limit: int = 25,
        lang: str = "",
        sort: str = "",
        sort_order: str = "",
        locc: str = "",
        author_id: Optional[int] = None,
        subject_id: Optional[int] = None,
        bookshelf_id: Optional[int] = None,
        modified_since: str = "",
        **_,
    ):
        """Full-text search."""
        page, limit = _paginate(page, limit)
        subject_id = _optional_int(subject_id)
        author_id = _optional_int(author_id)
        bookshelf_id = _optional_int(bookshelf_id)

        try:
            def scope(q):
                _search_scope(
                    q, query, title, author, locc, author_id, bookshelf_id
                )
                if modified_since:
                    q.modified_after(modified_since)
                return q

            facet_counts = self.catalog.get_opds_facets(
                scope, lang=lang, subject_id=subject_id
            )

            q = scope(self._query(OPDS_SMALL))
            if lang:
                q.lang(lang)
            if subject_id is not None:
                q.subject_id(subject_id)
            self._sort(q, sort, sort_order)
            result = self.catalog.execute(q[page, limit])
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
            "title": title,
            "author": author,
            "lang": lang,
            "sort": sort,
            "sort_order": sort_order,
            "locc": locc,
            "author_id": author_id,
            "subject_id": subject_id,
            "bookshelf_id": bookshelf_id,
            "modified_since": modified_since,
        }

        # Scope carried when narrowing to a Top Subject (subject_id is set by the
        # facet itself, so it's excluded here to allow switching subjects).
        search_scope = {
            "query": query,
            "title": title,
            "author": author,
            "locc": locc,
            "author_id": author_id,
            "bookshelf_id": bookshelf_id,
            "modified_since": modified_since,
        }
        facets = self._facets(
            _make_facet_url("/opds/search", base), query, lang, sort, sort_order,
            facet_counts["subjects"], facet_counts["languages"],
            search_scope, subject_id=subject_id,
        )
        return self._results_feed(
            "/opds/search", base, result, "/opds/", query=query, facets=facets
        )


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

    cherrypy.tree.mount(OPDSFeed(), "/opds", {"/": OPDS_MOUNT_CONFIG["/opds"]})
    try:
        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyboardInterrupt:
        cherrypy.engine.exit()
