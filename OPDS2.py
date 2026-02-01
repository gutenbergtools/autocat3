from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode
import logging
import time

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
LANGUAGES = [{"code": lang.code, "label": lang.label} for lang in Language]
VALID_SORTS = set(OrderBy._value2member_map_.keys())
OPDS_TYPE = "application/opds+json"
CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds


# Helpers
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
    def facet_url(q: str, lng: str, cr: str, ab: str, srt: str, so: str) -> str:
        return _url(endpoint, {
            **base,
            "query": q,
            "page": 1,
            "lang": lng,
            "copyrighted": cr,
            "audiobook": ab,
            "sort": srt,
            "sort_order": so,
        })
    return facet_url


def _paginate(page, limit, default=28) -> Tuple[int, int]:
    """Parse and clamp pagination params."""
    try:
        return max(1, int(page)), max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        return 1, default


def _search_type(field: str) -> SearchType:
    """Parse field param to SearchType."""
    if field.startswith("fts"):
        return SearchType.FTS
    return SearchType.FUZZY


def _sort_direction(order: str) -> Optional[SortDirection]:
    """Parse sort order string."""
    return {"asc": SortDirection.ASC, "desc": SortDirection.DESC}.get(order)


# CherryPy Search API
class OPDSFeed:
    def __init__(self):
        self._fts = None
        self._cache = {}
        self._cache_timestamp = 0

    def _initial_warm(self):
        """Run initial cache warm after engine starts."""
        try:
            self._warm_cache()
        except Exception as e:
            cherrypy.log(f"Initial cache warm failed: {e}", context='OPDS', severity=logging.ERROR)

    def _warm_cache(self):
        """Pre-warm cache for bookshelves, LoCC, and subjects."""
        cherrypy.log("Starting OPDS cache warm", context='OPDS', severity=logging.INFO)
        start = time.time()
        new_cache = {}

        try:
            # Warm bookshelf samples for each category
            for cat in CuratedBookshelves:
                for shelf_id, shelf_name in cat.shelves:
                    cache_key = f"bookshelf_sample_{shelf_id}"
                    try:
                        result = self.fts.execute(
                            self.fts.query(crosswalk=Crosswalk.OPDS)
                            .bookshelf_id(shelf_id)
                            .order_by(OrderBy.RANDOM)[1, SAMPLE_LIMIT]
                        )
                        new_cache[cache_key] = {
                            "result": result,
                            "count": result.get("total", 0)
                        }
                    except Exception as e:
                        cherrypy.log(f"Cache warm bookshelf {shelf_id}: {e}", context='OPDS', severity=logging.WARNING)

            # Warm LoCC navigation counts
            try:
                top_loccs = self.fts.get_locc_children("")
                for locc in top_loccs:
                    code = locc["code"]
                    cache_key = f"locc_children_{code}"
                    try:
                        children = self.fts.get_locc_children(code)
                        new_cache[cache_key] = children
                        # Cache counts for leaf nodes
                        for child in children:
                            if not child.get("has_children", False):
                                count_key = f"locc_count_{child['code']}"
                                new_cache[count_key] = self.fts.count(
                                    self.fts.query().locc(child["code"])
                                )
                    except Exception as e:
                        cherrypy.log(f"Cache warm LoCC {code}: {e}", context='OPDS', severity=logging.WARNING)
            except Exception as e:
                cherrypy.log(f"Cache warm LoCC top: {e}", context='OPDS', severity=logging.WARNING)

            # Warm subject list
            try:
                subjects = self.fts.list_subjects()
                new_cache["subjects_list"] = sorted(
                    subjects, key=lambda x: x["book_count"], reverse=True
                )
            except Exception as e:
                cherrypy.log(f"Cache warm subjects: {e}", context='OPDS', severity=logging.WARNING)

            self._cache = new_cache
            self._cache_timestamp = time.time()
            elapsed = time.time() - start
            cherrypy.log(f"OPDS cache warm complete: {len(new_cache)} items in {elapsed:.1f}s",
                        context='OPDS', severity=logging.INFO)

        except Exception as e:
            cherrypy.log(f"Cache warm error: {e}", context='OPDS', severity=logging.ERROR)

    def _get_cached(self, key: str, default=None):
        """Get a cached value if available."""
        return self._cache.get(key, default)

    @property
    def fts(self):
        if self._fts is None:
            self._fts = FullTextSearch(cherrypy.engine.pool.pool)
        return self._fts

    # Query Helpers
    def _filter(self, q, lang: str, copyrighted: str, audiobook: str):
        """Apply common filters to query."""
        if lang:
            q.lang(lang)
        if copyrighted == "true":
            q.copyrighted()
        elif copyrighted == "false":
            q.public_domain()
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
            cherrypy.log(f"Top subjects error: {e}", context='OPDS', severity=logging.WARNING)
            return None

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

    def _facets(
        self,
        url_fn: Callable,
        query: str,
        lang: str,
        copyrighted: str,
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
                        url_fn(
                            query, lang, copyrighted, audiobook, "downloads", "desc"
                        ),
                        "Most Popular",
                        sort in ("downloads", ""),
                    ),
                    _facet(
                        url_fn(query, lang, copyrighted, audiobook, "relevance", ""),
                        "Relevance",
                        sort == "relevance",
                    ),
                    _facet(
                        url_fn(query, lang, copyrighted, audiobook, "title", "asc"),
                        "Title (A-Z)",
                        sort == "title",
                    ),
                    _facet(
                        url_fn(query, lang, copyrighted, audiobook, "author", "asc"),
                        "Author (A-Z)",
                        sort == "author",
                    ),
                    _facet(
                        url_fn(query, lang, copyrighted, audiobook, "random", ""),
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
                            "title": f"{s['name']} ({s['count']})",
                        }
                        for s in subjects
                    ],
                }
            )

        facets.extend(
            [
                {
                    "metadata": {"title": "Copyright Status"},
                    "links": [
                        _facet(
                            url_fn(query, lang, "", audiobook, sort, sort_order),
                            "Any",
                            not copyrighted,
                        ),
                        _facet(
                            url_fn(query, lang, "false", audiobook, sort, sort_order),
                            "Public Domain",
                            copyrighted == "false",
                        ),
                        _facet(
                            url_fn(query, lang, "true", audiobook, sort, sort_order),
                            "Copyrighted",
                            copyrighted == "true",
                        ),
                    ],
                },
                {
                    "metadata": {"title": "Format"},
                    "links": [
                        _facet(
                            url_fn(query, lang, copyrighted, "", sort, sort_order),
                            "Any",
                            not audiobook,
                        ),
                        _facet(
                            url_fn(query, lang, copyrighted, "false", sort, sort_order),
                            "Text",
                            audiobook == "false",
                        ),
                        _facet(
                            url_fn(query, lang, copyrighted, "true", sort, sort_order),
                            "Audiobook",
                            audiobook == "true",
                        ),
                    ],
                },
                {
                    "metadata": {"title": "Language"},
                    "links": [
                        _facet(
                            url_fn(query, "", copyrighted, audiobook, sort, sort_order),
                            "Any",
                            not lang,
                        )
                        + [
                            _facet(
                                url_fn(
                                    query,
                                    item["code"],
                                    copyrighted,
                                    audiobook,
                                    sort,
                                    sort_order,
                                ),
                                item["label"],
                                lang == item["code"],
                            )
                            for item in LANGUAGES
                        ],
                    ],
                },
            ]
        )
        return facets

    # Index
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def index(self):
        """Root catalog."""
        return {
            "metadata": {"title": "Project Gutenberg Catalog"},
            "links": [
                _link("self", "/opds/"),
                _link("start", "/opds/"),
                _link("search", "/opds/search{?query}", templated=True),
            ],
            "navigation": [
                _nav(
                    "/opds/search?field=fuzzy",
                    "I'm not sure how to spell what I'm looking for",
                ),
                _nav("/opds/search?field=fts", "Advanced Search"),
                _nav("/opds/bookshelves", "Browse Bookshelves"),
                _nav("/opds/loccs", "Browse by Library of Congress Code"),
                _nav("/opds/subjects", "Browse by Subject"),
                _nav("/opds/search?audiobook=true&sort=downloads", "Browse Audiobooks"),
                {
                    "href": "/opds/search?sort=downloads&sort_order=desc",
                    "title": "Most Popular",
                    "type": OPDS_TYPE,
                    "rel": "http://opds-spec.org/sort/popular",
                },
                {
                    "href": "/opds/search?sort=release_date&sort_order=desc",
                    "title": "Recently Added",
                    "type": OPDS_TYPE,
                    "rel": "http://opds-spec.org/sort/new",
                },
                {
                    "href": "/opds/search?sort=random",
                    "title": "Random",
                    "type": OPDS_TYPE,
                    "rel": "http://opds-spec.org/sort/random",
                },
            ],
        }

    # Bookshelves
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def bookshelves(
        self,
        id: Optional[int] = None,
        category: Optional[str] = None,
        page: int = 1,
        limit: int = 28,
        query: str = "",
        lang: str = "",
        copyrighted: str = "",
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
                copyrighted,
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
                _nav(
                    f"/opds/bookshelves?category={cat.name}",
                    f"{cat.genre} ({len(cat.shelves)} shelves)",
                )
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
        copyrighted: str,
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
            if query.strip():
                q.search(query, search_type=_search_type("keyword"))
            self._filter(q, lang, copyrighted, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"Bookshelf error: {e}", context='OPDS', severity=logging.ERROR)
            raise cherrypy.HTTPError(500, "Browse failed")

        base = {
            "id": shelf_id,
            "limit": limit,
            "lang": lang,
            "copyrighted": copyrighted,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/bookshelves", base, query)
        facet_url = _make_facet_url("/opds/bookshelves", base)

        subjects_q = self.fts.query().bookshelf_id(shelf_id)
        if query.strip():
            subjects_q.search(query, search_type=_search_type("keyword"))
        self._filter(subjects_q, lang, copyrighted, audiobook)

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
                copyrighted,
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
            raise cherrypy.HTTPError(404, "Category not found")

        shelves = [{"id": s[0], "name": s[1]} for s in found.shelves]
        groups, counts = [], {}

        for s in shelves:
            cache_key = f"bookshelf_sample_{s['id']}"
            cached = self._get_cached(cache_key)

            if cached:
                counts[s["id"]] = cached["count"]
                if cached["result"].get("results"):
                    groups.append(
                        {
                            "metadata": {
                                "title": s["name"],
                                "numberOfItems": counts[s["id"]],
                            },
                            "links": [_link("self", f"/opds/bookshelves?id={s['id']}")],
                            "publications": cached["result"]["results"],
                        }
                    )
            else:
                try:
                    result = self.fts.execute(
                        self.fts.query(crosswalk=Crosswalk.OPDS)
                        .bookshelf_id(s["id"])
                        .order_by(OrderBy.RANDOM)[1, SAMPLE_LIMIT]
                    )
                    counts[s["id"]] = result.get("total", 0)
                    if result.get("results"):
                        groups.append(
                            {
                                "metadata": {
                                    "title": s["name"],
                                    "numberOfItems": counts[s["id"]],
                                },
                                "links": [_link("self", f"/opds/bookshelves?id={s['id']}")],
                                "publications": result["results"],
                            }
                        )
                except Exception as e:
                    cherrypy.log(f"Bookshelf sample error {s['id']}: {e}", context='OPDS', severity=logging.WARNING)
                    counts[s["id"]] = 0

        return {
            "metadata": {"title": found.genre, "numberOfItems": len(shelves)},
            "links": [
                _link("self", f"/opds/bookshelves?category={category}"),
                _link("start", "/opds/"),
                _link("up", "/opds/bookshelves"),
            ],
            "navigation": [
                _nav(
                    f"/opds/bookshelves?id={s['id']}",
                    f"{s['name']} ({counts.get(s['id'], 0)} books)",
                )
                for s in shelves
            ],
            "groups": groups,
        }

    # LoCC
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def loccs(
        self,
        parent: str = "",
        page: int = 1,
        limit: int = 28,
        query: str = "",
        lang: str = "",
        copyrighted: str = "",
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
            cherrypy.log(f"LoCC error: {e}", context='OPDS', severity=logging.ERROR)
            children = []

        if children:
            return self._locc_navigation(parent, children)

        return self._locc_books(
            parent, page, limit, query, lang, copyrighted, audiobook, sort, sort_order
        )

    def _locc_navigation(self, parent: str, children: List):
        """Build LoCC category navigation."""
        children.sort(key=lambda x: (len(x.get("code", "")), x.get("code", "")))

        # Get parent label from LoCCMainClass if it's a top-level code
        page_title = "Library of Congress Classification"
        if parent:
            for item in LoCCMainClass:
                if item.code == parent:
                    page_title = item.label
                    break
            else:
                page_title = f"Classification: {parent}"

        nav = []
        for child in children:
            code = child["code"]
            label = child.get("label", code)
            label = label.split(":", 1)[1].strip() if ":" in label else label
            has_children = child.get("has_children", False)

            if has_children:
                cached_children = self._get_cached(f"locc_children_{code}")
                if cached_children is not None:
                    count = len(cached_children)
                else:
                    count = len(self.fts.get_locc_children(code))
                nav_title = f"{label} ({count} subcategories)"
            else:
                cached_count = self._get_cached(f"locc_count_{code}")
                if cached_count is not None:
                    count = cached_count
                else:
                    count = self.fts.count(self.fts.query().locc(code))
                nav_title = f"{label} ({count} books)"

            nav.append(_nav(f"/opds/loccs?parent={code}", nav_title))

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
        copyrighted: str,
        audiobook: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books in a LoCC leaf."""
        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).locc(parent)
            if query.strip():
                q.search(query, search_type=_search_type("keyword"))
            self._filter(q, lang, copyrighted, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"LoCC browse error: {e}", context='OPDS', severity=logging.ERROR)
            raise cherrypy.HTTPError(500, "Browse failed")

        base = {
            "parent": parent,
            "limit": limit,
            "lang": lang,
            "copyrighted": copyrighted,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
        }
        page_url = _make_page_url("/opds/loccs", base, query)
        facet_url = _make_facet_url("/opds/loccs", base)

        subjects_q = self.fts.query().locc(parent)
        if query.strip():
            subjects_q.search(query, search_type=_search_type("keyword"))
        self._filter(subjects_q, lang, copyrighted, audiobook)

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
                copyrighted,
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
    @cherrypy.tools.json_out()
    def subjects(
        self,
        id: Optional[int] = None,
        page: int = 1,
        limit: int = 28,
        query: str = "",
        lang: str = "",
        copyrighted: str = "",
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
                copyrighted,
                audiobook,
                sort,
                sort_order,
            )

        cached_subjects = self._get_cached("subjects_list")
        if cached_subjects is not None:
            subjects = cached_subjects
        else:
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
                _nav(
                    f"/opds/subjects?id={s['id']}",
                    f"{s['name']} ({s['book_count']} books)",
                )
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
        copyrighted: str,
        audiobook: str,
        sort: str,
        sort_order: str,
    ):
        """Browse books for a subject."""
        name = self.fts.get_subject_name(subject_id) or f"Subject {subject_id}"

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS).subject_id(subject_id)
            if query.strip():
                q.search(query, search_type=_search_type("keyword"))
            self._filter(q, lang, copyrighted, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])
        except Exception as e:
            cherrypy.log(f"Subject error: {e}", context='OPDS', severity=logging.ERROR)
            raise cherrypy.HTTPError(500, "Browse failed")

        base = {
            "id": subject_id,
            "limit": limit,
            "lang": lang,
            "copyrighted": copyrighted,
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
            "facets": self._facets(
                facet_url, query, lang, copyrighted, audiobook, sort, sort_order
            ),
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed

    # Search

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def search(
        self,
        query: str = "",
        page: int = 1,
        limit: int = 28,
        field: str = "fuzzy",
        lang: str = "",
        copyrighted: str = "",
        audiobook: str = "",
        sort: str = "",
        sort_order: str = "",
        locc: str = "",
    ):
        """Full-text search."""
        page, limit = _paginate(page, limit)
        stype = _search_type(field)

        try:
            q = self.fts.query(crosswalk=Crosswalk.OPDS)
            if query.strip():
                q.search(query, search_type=stype)
            if locc:
                q.locc(locc)
            self._filter(q, lang, copyrighted, audiobook)
            self._sort(q, sort, sort_order)
            result = self.fts.execute(q[page, limit])

            subjects = None
            if query.strip() or locc or lang:
                sq = self.fts.query()
                if query.strip():
                    sq.search(query, search_type=stype)
                if locc:
                    sq.locc(locc)
                self._filter(sq, lang, copyrighted, audiobook)
                subjects = self._top_subjects(sq)
        except Exception as e:
            cherrypy.log(f"Search error: {e}", context='OPDS', severity=logging.ERROR)
            raise cherrypy.HTTPError(500, "Search failed")

        base = {
            "limit": limit,
            "field": field,
            "lang": lang,
            "copyrighted": copyrighted,
            "audiobook": audiobook,
            "sort": sort,
            "sort_order": sort_order,
            "locc": locc,
        }
        page_url = _make_page_url("/opds/search", base, query)
        facet_url = _make_facet_url("/opds/search", base)

        facets = self._facets(
            facet_url, query, lang, copyrighted, audiobook, sort, sort_order, subjects
        )

        # LoCC genre facet - only show when no category selected
        if not locc:
            locc_base = {**base, "query": query, "page": 1}
            locc_facet = {
                "metadata": {"title": "Main Category"},
                "links": [
                    _facet(
                        _url("/opds/search", {**locc_base, "locc": item.code}),
                        item.label,
                        False,
                    )
                    for item in LoCCMainClass
                ],
            }
            facets.insert(2 if subjects else 1, locc_facet)

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
                _link(
                    "search", f"/opds/search?field={field}{{&query}}", templated=True
                ),
            ],
            "publications": result["results"],
            "facets": facets,
        }
        feed["links"].extend(
            self._pagination_links(page_url, result["page"], result["total_pages"])
        )
        return feed


if __name__ == "__main__":
    cherrypy.config.update(
        {"server.socket_host": "0.0.0.0", "server.socket_port": 8080}
    )

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

    feed = OPDSFeed()
    feed.start_background_task()

    cherrypy.tree.mount(
        feed,
        "/opds",
        {
            "/": {
                "tools.cors.on": True,
                "request.methods_with_bodies": ("POST", "PUT", "PATCH"),
            }
        },
    )
    try:
        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyboardInterrupt:
        cherrypy.engine.exit()
