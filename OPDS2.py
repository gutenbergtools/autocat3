"""
OPDS2.py — Zachary Rosario

OPDS 2.0 JSON feed for the Project Gutenberg catalog.
"""

import datetime
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
    SearchField,
    SearchType,
    SortDirection,
)
from mv_search.Search import FullTextSearch

SAMPLE_LIMIT = 15
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
LANGUAGE_LABELS = {lang.code: lang.label for lang in Language}

VALID_SORTS = set(OrderBy._value2member_map_.keys())
OPDS_TYPE = "application/opds+json"
OPDS_PUBLICATION_TYPE = "application/opds-publication+json"
# Only the user-facing search fields are advertised to clients. /opds/search
# also accepts lang, sort, sort_order, locc, author_id, subject_id
# and bookshelf_id for internal facet/scope carry-over, but those are kept out
# of the template so clients don't surface them as search inputs.
SEARCH_TEMPLATE = "/opds/search{?query,title,author}"


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


def _make_page_url(endpoint: str, base: Dict, query: str = "") -> Callable[[int], str]:
    """Create a page URL builder for pagination links."""

    def page_url(p: int) -> str:
        return _url(endpoint, {**base, "query": query, "page": p})

    return page_url


def _make_facet_url(endpoint: str, base: Dict) -> Callable[..., str]:
    """Create a facet URL builder for filter facets."""

    def facet_url(q: str, lng: str, srt: str, so: str) -> str:
        return _url(
            endpoint,
            {
                **base,
                "query": q,
                "page": 1,
                "lang": lng,
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


def _daily_seed() -> int:
    """Day number used to rotate shelves once per day."""
    return datetime.date.today().toordinal()


def _book_id(pub: Dict) -> Optional[int]:
    """Extract the numeric Gutenberg id from an OPDS publication."""
    try:
        ident = pub["metadata"]["identifier"]
        if isinstance(ident, str) and "/ebooks/" in ident:
            return int(ident.rstrip("/").rsplit("/", 1)[-1])
    except (KeyError, ValueError, AttributeError, TypeError):
        pass
    return None


# CherryPy Search API
class OPDSFeed:
    _CACHE_TTL = datetime.timedelta(hours=12)

    def __init__(self):
        self._fts = None
        self._feed_cache = {}  # key -> (expires, feed)
        self._facet_cache = {}  # key -> (expires, (languages, subjects))

    @property
    def fts(self):
        if self._fts is None:
            self._fts = FullTextSearch(cherrypy.engine.pool.pool)
        return self._fts

    # Query Helpers
    def _filter(self, q, lang: str):
        """Apply common filters to query."""
        if lang:
            q.lang(lang)
        return q

    def _sort(self, q, sort: str, sort_order: str):
        """Apply sorting to query."""
        if sort in VALID_SORTS:
            q.order_by(OrderBy(sort), _sort_direction(sort_order))
        else:
            q.order_by(OrderBy.DOWNLOADS)
        return q

    def _cache_feed(
        self,
        key: str,
        build: Callable[[], Dict],
        *,
        store: Callable[[Dict], bool],
    ) -> Dict:
        """Return a cached feed with a 12-hour TTL."""
        hit = self._feed_cache.get(key)
        if hit and datetime.datetime.now() < hit[0]:
            return hit[1]
        feed = build()
        if store(feed):
            self._feed_cache[key] = (
                datetime.datetime.now() + self._CACHE_TTL,
                feed,
            )
        return feed

    def _get_cached_facets(self, key: Tuple):
        hit = self._facet_cache.get(key)
        if hit and datetime.datetime.now() < hit[0]:
            return hit[1]
        return None

    def _set_cached_facets(self, key: Tuple, languages, subjects) -> None:
        self._facet_cache[key] = (
            datetime.datetime.now() + self._CACHE_TTL,
            (languages, subjects),
        )

    def _search_facet_key(
        self,
        query: str,
        title: str,
        author: str,
        locc: str,
        author_id: Optional[int],
        subject_id: Optional[int],
        bookshelf_id: Optional[int],
        lang: str,
        sort: str,
        sort_order: str,
    ) -> Tuple:
        """Cache key for /opds/search facet queries (page omitted; facets do not change when paginating)."""
        return (
            "search",
            query.strip(),
            title.strip(),
            author.strip(),
            locc or "",
            author_id,
            subject_id,
            bookshelf_id,
            lang or "",
            sort or "",
            sort_order or "",
        )

    def _shelf_sample(self, shelf_id: int, seen: set, with_count: bool) -> Dict:
        """Top-downloaded sample for a shelf, excluding already-shown books."""
        q = self.fts.query(crosswalk=Crosswalk.OPDS).bookshelf_id(shelf_id)
        if seen:
            q.where("book_id <> ALL(:seen_ids)", seen_ids=list(seen))
        result = self.fts.execute(
            q.order_by(OrderBy.DOWNLOADS)[1, SAMPLE_LIMIT], with_count=with_count
        )
        for pub in result.get("results", []):
            bid = _book_id(pub)
            if bid is not None:
                seen.add(bid)
        return result

    def _category_count(self, cat) -> int:
        """Count distinct books across all of a category's sub-shelves."""
        try:
            q = self.fts.query().where(
                "EXISTS (SELECT 1 FROM mn_books_bookshelves mbb "
                "WHERE mbb.fk_books = book_id "
                "AND mbb.fk_bookshelves = ANY(:shelf_ids))",
                shelf_ids=[sid for sid, _ in self.fts.curated_shelves(cat)],
            )
            return self.fts.count(q)
        except Exception:
            return 0

    def _top_subjects(self, q) -> Optional[List[Dict]]:
        """Top 10 subjects across all matching books (no book sampling)."""
        try:
            return self.fts.get_top_subjects_for_query(q, limit=10)
        except Exception as e:
            cherrypy.log(f"Top subjects error: {e}")
            return None

    def _top_languages(self, q) -> Optional[List[Dict]]:
        """All languages present across all matching books (no book sampling)."""
        try:
            return self.fts.get_languages_for_query(q)
        except Exception as e:
            cherrypy.log(f"Top languages error: {e}")
            return None

    def _locc_counts(self, parent: str, children: List[Dict]) -> Dict[str, int]:
        """Per-child book counts via FTS. Skipped at the top level, where each
        main class would be one large full-class aggregation."""
        if not parent:
            return {}
        counts = {}
        for child in children:
            code = child["code"]
            try:
                counts[code] = self.fts.count(self.fts.query().locc(code))
            except Exception as e:
                cherrypy.log(
                    f"LoCC nav count error ({code}): {e}", severity=logging.WARNING
                )
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
                url_fn(query, lang, "downloads", "desc"),
                "Most Popular",
                sort in ("downloads", ""),
            ),
            _facet(
                url_fn(query, lang, "release_date", "desc"),
                "Newest",
                sort == "release_date",
            ),
        ]
        if query:
            sort_links.extend(
                [
                    _facet(
                        url_fn(query, lang, "relevance", ""),
                        "Relevance",
                        sort == "relevance",
                    ),
                    _facet(
                        url_fn(query, lang, "title", "asc"),
                        "Title (A-Z)",
                        sort == "title",
                    ),
                    _facet(
                        url_fn(query, lang, "author", "asc"),
                        "Author (A-Z)",
                        sort == "author",
                    ),
                ]
            )
        sort_links.append(
            _facet(
                url_fn(query, lang, "random", ""),
                "Random",
                sort == "random",
            )
        )
        facets = [
            {
                "metadata": {"title": "Sort By"},
                "links": sort_links,
            }
        ]

        if subjects:
            subject_links = [
                {
                    "href": _url(
                        "/opds/search",
                        {
                            **(scope or {}),
                            "subject_id": s["id"],
                            "lang": lang,
                            "sort": sort,
                            "sort_order": sort_order,
                        },
                    ),
                    "type": OPDS_TYPE,
                    "title": s["name"],
                    "properties": {"numberOfItems": s["count"]},
                }
                for s in subjects
            ]
            if subject_id is not None:
                subject_links.append(
                    _facet(
                        _url(
                            "/opds/search",
                            {
                                **(scope or {}),
                                "lang": lang,
                                "sort": sort,
                                "sort_order": sort_order,
                            },
                        ),
                        "None",
                        False,
                    )
                )
            facets.append(
                {
                    "metadata": {"title": "Top Subjects in Results"},
                    "links": subject_links,
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
        links = [
            _facet(url_fn(query, "", sort, sort_order), "Any", not lang)
        ]
        if languages is not None:
            items = [
                (item["code"], LANGUAGE_LABELS.get(item["code"], item["code"]),
                 item.get("count"))
                for item in languages
            ]
        else:
            items = [(item["code"], item["label"], None) for item in LANGUAGES]

        for code, label, count in items:
            link = _facet(
                url_fn(query, code, sort, sort_order),
                label,
                lang == code,
            )
            if count is not None:
                link["properties"] = {"numberOfItems": count}
            links.append(link)
        return links

    # Index
    @cherrypy.expose
    def index(self):
        """Root catalog."""
        return self._cache_feed(
            "index", self._build_index, store=lambda feed: bool(feed.get("groups"))
        )

    def _build_index(self):
        seen = set()
        day = _daily_seed()

        def _mark_seen(results):
            for pub in results:
                bid = _book_id(pub)
                if bid is not None:
                    seen.add(bid)

        def _recently_added():
            result = self.fts.execute(
                self.fts.query(crosswalk=Crosswalk.OPDS).order_by(
                    OrderBy.RELEASE_DATE, SortDirection.DESC
                )[1, SAMPLE_LIMIT],
            )
            if result.get("results"):
                _mark_seen(result["results"])
                return {
                    "metadata": {
                        "title": "Recently Added",
                        "numberOfItems": result["total"],
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
            )
            if result.get("results"):
                _mark_seen(result["results"])
                return {
                    "metadata": {
                        "title": "Most Popular",
                        "numberOfItems": result["total"],
                    },
                    "links": [
                        _link("self", "/opds/search?sort=downloads&sort_order=desc")
                    ],
                    "publications": result["results"],
                }

        def _category_group(cat):
            """Daily spotlight shelf (rotates by date), top picks, deduped."""
            shelves = self.fts.curated_shelves(cat)
            if not shelves:
                return

            for offset in range(len(shelves)):
                shelf_id, _shelf_name = shelves[(day + offset) % len(shelves)]
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
                                    f"/opds/bookshelves?category={cat.name}",
                                )
                            ],
                            "publications": result["results"],
                        }
                except Exception as e:
                    cherrypy.log(
                        f"Index group error ({cat.name}/{shelf_id}): {e}",
                        severity=logging.WARNING,
                    )

        tasks = [_recently_added, _most_popular] + [
            lambda c=cat: _category_group(c) for cat in CuratedBookshelves
        ]

        groups = []
        for fn in tasks:
            try:
                result = fn()
                if result:
                    groups.append(result)
            except Exception as e:
                cherrypy.log(f"Index group error: {e}")

        return {
            "metadata": {"title": "Project Gutenberg"},
            "links": [
                _link("self", "/opds/"),
                _link("start", "/opds/"),
                _link("search", SEARCH_TEMPLATE, templated=True),
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
        lang: str = "",
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
                lang,
                sort,
                sort_order,
            )
        if category is not None:
            return self._bookshelf_category(category)

        return {
            "metadata": {
                "title": "Project Gutenberg",
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
                    "properties": {"numberOfItems": len(cat.shelf_names)},
                }
                for cat in CuratedBookshelves
            ],
        }

    def _bookshelf_books(
        self,
        shelf_id: int,
        page: int,
        limit: int,
        lang: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books in a bookshelf."""
        parent = None
        for cat in CuratedBookshelves:
            if any(sid == shelf_id for sid, _ in self.fts.curated_shelves(cat)):
                parent = cat.name
                break

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).bookshelf_id(shelf_id)
            self._filter(q, lang)
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
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/bookshelves", base)
        facet_url = _make_facet_url("/opds/bookshelves", base)

        subjects_q = self.fts.query().bookshelf_id(shelf_id)
        self._filter(subjects_q, lang)
        lang_q = self.fts.query().bookshelf_id(shelf_id)

        up = f"/opds/bookshelves?category={parent}" if parent else "/opds/bookshelves"
        feed = {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", up),
                _link("search", SEARCH_TEMPLATE, templated=True),
            ],
            "publications": result["results"],
            "facets": self._facets(
                facet_url,
                "",
                lang,
                sort,
                sort_order,
                self._top_subjects(subjects_q),
                self._top_languages(lang_q),
                {"bookshelf_id": shelf_id},
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    def _bookshelf_category(self, category: str):
        """List shelves in a category with daily spotlight samples (cached)."""
        found = next((cat for cat in CuratedBookshelves if cat.name == category), None)
        if not found:
            return self._error_feed(
                "Category not found",
                f"Bookshelf category {category} was not found.",
                f"/opds/bookshelves?category={category}",
                "/opds/bookshelves",
                status=404,
            )

        def build():
            seen = set()
            day = _daily_seed()
            shelves = self.fts.curated_shelves(found)
            if not shelves:
                return {"groups": []}
            rotated = [shelves[(day + i) % len(shelves)] for i in range(len(shelves))]
            groups = []
            for sid, sname in rotated:
                try:
                    result = self._shelf_sample(sid, seen, with_count=True)
                    if result.get("results"):
                        groups.append(
                            {
                                "metadata": {
                                    "title": sname,
                                    "numberOfItems": result["total"],
                                },
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
                    "numberOfItems": len(found.shelf_names),
                },
                "links": [
                    _link("self", f"/opds/bookshelves?category={category}"),
                    _link("start", "/opds/"),
                    _link("up", "/opds/bookshelves"),
                ],
                "groups": groups,
            }

        return self._cache_feed(
            f"cat:{category}", build, store=lambda feed: bool(feed.get("groups"))
        )

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
            parent, page, limit, lang, sort, sort_order
        )

    def _locc_navigation(self, parent: str, children: List):
        """Build LoCC category navigation."""
        children.sort(key=lambda x: (len(x.get("code", "")), x.get("code", "")))

        counts = self._locc_counts(parent, children)

        nav = []
        for child in children:
            code = child["code"]
            label = child.get("label") or code
            prefix, sep, rest = label.partition(":")
            if sep and prefix.strip().upper() == code.upper():
                label = rest.strip()

            # Below the top level, drop the redundant main-class prefix the
            # parent crumb already conveys. Try the full label first (e.g.
            # "History: America:"), then just its lead segment ("History:").
            # DB locc strings use "Language and Literatures:" (plural); see LoCCMainClass.P.
            if parent:
                main = code[0].upper() if code else ""
                mc = next((i for i in LoCCMainClass if i.code == main), None)
                if mc:
                    for cand in (mc.label.strip(), mc.label.split(":", 1)[0].strip()):
                        if cand and label.upper().startswith(cand.upper() + ":"):
                            label = label[len(cand) + 1 :].strip()
                            break

            nav_item = _nav(f"/opds/loccs?parent={code}", label)
            if code in counts:
                nav_item["properties"] = {"numberOfItems": counts[code]}
            nav.append(nav_item)

        return {
            "metadata": {"title": "Project Gutenberg", "numberOfItems": len(children)},
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
        lang: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books in a LoCC leaf."""
        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).locc(parent)
            self._filter(q, lang)
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
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/loccs", base)
        facet_url = _make_facet_url("/opds/loccs", base)

        subjects_q = self.fts.query().locc(parent)
        self._filter(subjects_q, lang)
        lang_q = self.fts.query().locc(parent)

        feed = {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/loccs"),
                _link("search", SEARCH_TEMPLATE, templated=True),
            ],
            "publications": result["results"],
            "facets": self._facets(
                facet_url,
                "",
                lang,
                sort,
                sort_order,
                self._top_subjects(subjects_q),
                self._top_languages(lang_q),
                {"locc": parent},
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    # Subjects

    def _build_subjects_index(self) -> Dict:
        subjects = sorted(
            self.fts.list_subjects(), key=lambda x: x["book_count"], reverse=True
        )
        return {
            "metadata": {"title": "Project Gutenberg", "numberOfItems": len(subjects)},
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

    @cherrypy.expose
    def subjects(
        self,
        id: Optional[int] = None,
        page: int = 1,
        limit: int = 25,
        lang: str = "",
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
                lang,
                sort,
                sort_order,
            )

        return self._build_subjects_index()

    def _subject_books(
        self,
        subject_id: int,
        page: int,
        limit: int,
        lang: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books for a subject."""
        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).subject_id(subject_id)
            self._filter(q, lang)
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
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/subjects", base)
        facet_url = _make_facet_url("/opds/subjects", base)

        lang_q = self.fts.query().subject_id(subject_id)

        feed = {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/subjects"),
                _link("search", SEARCH_TEMPLATE, templated=True),
            ],
            "publications": result["results"],
            "facets": self._facets(
                facet_url,
                "",
                lang,
                sort,
                sort_order,
                languages=self._top_languages(lang_q),
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    # Publications

    @cherrypy.expose
    def publications(self, id: int):
        """Single publication by Gutenberg ebook number."""
        try:
            result = self.fts.execute(
                self.fts.query(crosswalk=Crosswalk.OPDS).etext(int(id))[1, 1]
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
    ):
        """Full-text search."""
        page, limit = _paginate(page, limit)

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS)
            if query.strip():
                q.search(query, search_type=SearchType.HYBRID)
            if title.strip():
                q.search(
                    title, field=SearchField.TITLE, search_type=SearchType.HYBRID
                )
            if author.strip():
                q.search(
                    author, field=SearchField.AUTHOR, search_type=SearchType.HYBRID
                )

            if locc:
                q.locc(locc)
            if author_id is not None:
                q.author_id(int(author_id))
            if subject_id is not None:
                q.subject_id(int(subject_id))
            if bookshelf_id is not None:
                q.bookshelf_id(int(bookshelf_id))

            facet_key = self._search_facet_key(
                query,
                title,
                author,
                locc,
                author_id,
                subject_id,
                bookshelf_id,
                lang,
                sort,
                sort_order,
            )
            cached = self._get_cached_facets(facet_key)
            if cached is not None:
                languages, subjects = cached
                if lang:
                    q.lang(lang)
            else:
                languages = self._top_languages(q)
                if lang:
                    q.lang(lang)
                subjects = self._top_subjects(q)
                self._set_cached_facets(facet_key, languages, subjects)

            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
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
        }
        page_url = _make_page_url("/opds/search", base, query)
        facet_url = _make_facet_url("/opds/search", base)

        # Scope carried when narrowing to a Top Subject (subject_id is set by the
        # facet itself, so it's excluded here to allow switching subjects).
        scope = {
            "query": query,
            "title": title,
            "author": author,
            "locc": locc,
            "author_id": author_id,
            "bookshelf_id": bookshelf_id,
        }
        facets = self._facets(
            facet_url, query, lang, sort, sort_order, subjects, languages,
            scope, subject_id=subject_id,
        )

        feed = {
            "metadata": {
                "title": "Project Gutenberg",
                "numberOfItems": result["total"],
                "itemsPerPage": result["page_size"],
                "currentPage": result["page"],
            },
            "links": [
                _link("self", page_url(result["page"])),
                _link("start", "/opds/"),
                _link("up", "/opds/"),
                _link("search", SEARCH_TEMPLATE, templated=True),
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
