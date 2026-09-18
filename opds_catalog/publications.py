"""
publications.py — Zachary Rosario

mv_books_dc row -> OPDS 2.0 publication dicts, plus the text clean-up helpers
they use (based on libgutenberg.DublinCore).
"""

import re
from functools import wraps
from itertools import zip_longest
from typing import Any, Callable, Dict, List, Optional

import cherrypy

from .constants import BOOKSHELF_CATEGORY_PREFIX, Crosswalk, LoCCMainClass

_LOCC_LABELS = {item.code: item.label for item in LoCCMainClass}

# Readium Web Publication Manifest subject schemes
SCHEME_LCC = "http://purl.org/dc/terms/LCC"
SCHEME_GUTENBERG_SUBJECT = "https://www.gutenberg.org/ebooks/subject/"
SCHEME_GUTENBERG_BOOKSHELF = "https://www.gutenberg.org/ebooks/bookshelf/"

_OPDS_FEED_TYPE = "application/opds+json"
_OPDS_PUBLICATION_TYPE = "application/opds-publication+json"
_OPDS_ACQUISITION_REL = "http://opds-spec.org/acquisition/open-access"

# PG-generated cover JPEGs (fixed output sizes from ebookconverter). Every
# book with an epub3.images file also has both covers, always at
# /cache/epub/{id}/pg{id}.cover.{size}.jpg, so they are derived from the
# book id rather than materialized in mv_books_dc.
_COVER_SPECS = (
    ("medium", 200, 288, "http://opds-spec.org/image"),
    ("small", 66, 95, "http://opds-spec.org/image/thumbnail"),
)


# =============================================================================
# Text clean-up (MARC subfields, curly quotes, separators)
# =============================================================================

_RE_MARC_SUBFIELD = re.compile(r"\$[a-z]")
_RE_MARC_SPSEP = re.compile(r"[\n ](,|:)([A-Za-z0-9])")
_RE_CURLY_SINGLE = re.compile("[\u2018\u2019]")
_RE_CURLY_DOUBLE = re.compile("[\u201c\u201d]")
_RE_TITLE_SPLITTER = re.compile(r"\s*[;:]\s*")
_RE_PARENS = re.compile(r"\(.*\)")
_RE_MULTI_SPACE = re.compile(r"\s+")

# Dict keys whose string values get MARC/quote clean-up in crosswalk output.
_FIELDS_TO_FORMAT = frozenset(
    {
        "title",
        "name",  # contributor names
        "publisher",  # MARC 260/264
        "summary",  # MARC 520
        "reading_level",  # MARC 908
        "subject",
        "subjects",
        "bookshelf",
        "bookshelves",
    }
)


def strip_marc_subfields(text: str) -> str:
    """Strip MARC subfield markers ($a, $b, etc)."""
    if not text or not isinstance(text, str):
        return ""
    text = _RE_MARC_SUBFIELD.sub("", text)
    text = _RE_MARC_SPSEP.sub(r"\1 \2", text)
    return text.strip()


def normalize_text(text: str) -> str:
    """Straighten curly quotes, normalize title separators."""
    if not text or not isinstance(text, str):
        return ""
    text = _RE_CURLY_SINGLE.sub("'", text)
    text = _RE_CURLY_DOUBLE.sub('"', text)
    text = _RE_TITLE_SPLITTER.sub(": ", text)
    return text.rstrip(": ").strip()


def format_field(key: str, value: str, fields: frozenset = _FIELDS_TO_FORMAT) -> str:
    if not value or not isinstance(value, str):
        return ""
    if key in fields:
        value = strip_marc_subfields(value)
        value = normalize_text(value)
    return value.strip()


def format_dict(d: Dict, fields: frozenset = _FIELDS_TO_FORMAT) -> Dict:
    """Recursively format dict values."""
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = format_field(key, value, fields)
        elif isinstance(value, dict):
            result[key] = format_dict(value, fields)
        elif isinstance(value, list):
            result[key] = format_list(key, value, fields)
        else:
            result[key] = value
    return result


def format_list(
    parent_key: str, lst: List, fields: frozenset = _FIELDS_TO_FORMAT
) -> List:
    """Recursively format list items."""
    result = []
    for item in lst:
        if isinstance(item, dict):
            result.append(format_dict(item, fields))
        elif isinstance(item, str):
            result.append(format_field(parent_key, item, fields))
        elif isinstance(item, list):
            result.append(format_list(parent_key, item, fields))
        else:
            result.append(item)
    return result


def format_dict_result(
    fn: Optional[Callable] = None, *, fields_to_format: frozenset = _FIELDS_TO_FORMAT
) -> Callable:
    """Decorator that formats dict results."""
    fields_fs = frozenset(fields_to_format)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                return format_dict(result, fields_fs)
            return result

        return wrapper

    if fn is None:
        return decorator
    return decorator(fn)


# =============================================================================
# Creator display string ("Creators: ..." line of the description)
# =============================================================================


def _format_date_range(floor: Optional[int], ceil: Optional[int]) -> str:
    """Format birth/death year with uncertainty."""
    if ceil and not floor:
        if ceil < 0:
            return f"{abs(ceil - 1)}? BCE"
        return f"{ceil}?"
    if not floor:
        return ""
    if ceil and floor != ceil:
        d = max(floor, ceil)
        if d < 0:
            return f"{abs(d - 1)}? BCE"
        return f"{d}?"
    if floor < 0:
        return f"{abs(floor - 1)} BCE"
    return str(floor)


def _reverse_name(name: str) -> str:
    """Reverse 'Twain, Mark' -> 'Mark Twain', dropping parenthesized text."""
    if not name:
        return ""
    rev = " ".join(reversed(name.split(", ")))
    rev = _RE_PARENS.sub("", rev)
    rev = _RE_MULTI_SPACE.sub(" ", rev)
    return rev.strip()


def _format_creator(c: Dict[str, Any]) -> str:
    """'Mark Twain (1835-1910) [Editor]'; role omitted for authors."""
    result = _reverse_name(c.get("name", ""))
    born = _format_date_range(c.get("born_floor"), c.get("born_ceil"))
    died = _format_date_range(c.get("died_floor"), c.get("died_ceil"))
    if born and died:
        result += f" ({born}-{died})"
    elif born:
        result += f" ({born}-)"
    elif died:
        result += f" (d. {died})"
    role = c.get("role")
    if role and role.lower() not in ("author", "creator", "aut", "cre"):
        result += f" [{role}]"
    return result


def format_creators(creators: List[Dict[str, Any]]) -> str:
    """Oxford-comma list of creators: 'A', 'A and B', 'A, B, and C'."""
    items = [_format_creator(c) for c in creators if c.get("name")]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


# =============================================================================
# URLs
# =============================================================================


def _abs_url(base: str, path: str) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return f"{base.rstrip('/')}{path if path.startswith('/') else '/' + path}"


def _host_url(config_key: str, path: str) -> str:
    host = cherrypy.config.get(config_key, "www.gutenberg.org")
    base = host if host.startswith(("http://", "https://")) else f"https://{host}"
    return _abs_url(base, path)


def _gutenberg_url(path: str) -> str:
    """Absolute URL for files/covers (file_host, usually gutenberg.org)."""
    return _host_url("file_host", path)


def _catalog_url(path: str) -> str:
    """Absolute URL for OPDS routes (catalog host from config)."""
    return _host_url("host", path)


# =============================================================================
# Row parsing
# =============================================================================


def _cols(row, *names) -> List[List[Any]]:
    """Array columns as lists (None -> [])."""
    return [list(getattr(row, n)) if getattr(row, n) else [] for n in names]


def _build_creators(row) -> List[Dict[str, Any]]:
    cols = _cols(
        row,
        "creator_names", "creator_roles", "creator_ids",
        "creator_born_floor", "creator_born_ceil",
        "creator_died_floor", "creator_died_ceil",
    )
    return [
        {
            "id": cid,
            "name": name,
            "role": role,
            "born_floor": bf,
            "born_ceil": bc,
            "died_floor": df,
            "died_ceil": dc,
        }
        for name, role, cid, bf, bc, df, dc in zip_longest(*cols, fillvalue=None)
        if name
    ]


def _build_creators_slim(row) -> List[Dict[str, Any]]:
    cols = _cols(row, "creator_names", "creator_roles", "creator_ids")
    return [
        {"id": cid, "name": name, "role": role}
        for name, role, cid in zip_longest(*cols, fillvalue=None)
        if name
    ]


def _build_subjects(row) -> List[Dict[str, Any]]:
    names, ids = _cols(row, "subject_names", "subject_ids")
    return [
        {"id": sid, "subject": name}
        for name, sid in zip_longest(names, ids, fillvalue=None)
        if name
    ]


def _build_bookshelves(row) -> List[Dict[str, Any]]:
    names, ids = _cols(row, "bookshelf_names", "bookshelf_ids")
    return [
        {"id": bid, "bookshelf": name}
        for name, bid in zip_longest(names, ids, fillvalue=None)
        if name
    ]


def _build_formats(row) -> List[Dict[str, Any]]:
    cols = _cols(
        row,
        "format_filenames", "format_filetypes", "format_hr_filetypes",
        "format_mediatypes", "format_extents",
    )
    return [
        {
            "filename": fn,
            "filetype": ftype,
            "hr_filetype": hr,
            "mediatype": med,
            "extent": extent,
        }
        for fn, ftype, hr, med, extent in zip_longest(*cols, fillvalue=None)
        if fn
    ]


# =============================================================================
# OPDS publication pieces
# =============================================================================


def _rights_text(copyrighted: Optional[int]) -> str:
    return (
        "Copyrighted. Read the copyright notice inside this book for details."
        if copyrighted
        else "Public domain in the USA."
    )


def _opds_book_metadata(row) -> Dict[str, Any]:
    return {
        "@type": "http://schema.org/Book",
        "identifier": _gutenberg_url(f"/ebooks/{row.book_id}"),
        "title": row.title,
        "language": (list(row.lang_codes) if row.lang_codes else ["en"])[0] or "en",
    }


def _opds_accessibility() -> Dict[str, Any]:
    return {
        "hazard": ["none"],
        "accessMode": ["textual"],
        "accessModeSufficient": [["textual"]],
        "feature": ["displayTransformability", "unlocked"],
    }


# Readium Web Publication Manifest contributor fields.
# creator_roles in mv_books_dc uses full MARC relator labels (e.g. "Author",
# "Illustrator"). Roles without a direct WPM field map to "contributor".
_OPDS_ROLE_FIELDS = {
    "author": "author",
    "creator": "author",
    "dubious author": "author",
    "translator": "translator",
    "editor": "editor",
    "artist": "artist",
    "illustrator": "illustrator",
    "letterer": "letterer",
    "penciler": "penciler",
    "colorist": "colorist",
    "inker": "inker",
}


def _opds_role_field(role: Optional[str]) -> str:
    if not role:
        return "contributor"
    return _OPDS_ROLE_FIELDS.get(role.strip().lower(), "contributor")


def _build_opds_contributor_entry(
    person: Dict[str, Any], *, with_search_link: bool = False
) -> Dict[str, Any]:
    contributor = {"name": person["name"], "sortAs": person["name"]}
    if with_search_link and person.get("id"):
        contributor["identifier"] = _gutenberg_url(f"/ebooks/author/{person['id']}")
        contributor["links"] = [
            {
                "href": _catalog_url(f"/opds/search?author_id={person['id']}"),
                "type": _OPDS_FEED_TYPE,
            }
        ]
    return contributor


def _set_publication_contributors(
    publication_metadata: Dict[str, Any],
    creators: List[Dict[str, Any]],
    *,
    with_search_link: bool = False,
) -> None:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for person in creators:
        if not person.get("name"):
            continue
        field = _opds_role_field(person.get("role"))
        grouped.setdefault(field, []).append(
            _build_opds_contributor_entry(person, with_search_link=with_search_link)
        )

    for field, entries in grouped.items():
        publication_metadata[field] = entries[0] if len(entries) == 1 else entries


def _opds_description(row, creators: List[Dict[str, Any]]) -> Optional[str]:
    """Plain-text description; JSON serialization escapes special characters."""
    desc_parts = []
    if creators:
        desc_parts.append(f"Creators: {format_creators(creators)}")
    summary = (list(row.summary) if row.summary else [None])[0]
    if summary:
        desc_parts.append(summary)
    if row.reading_level:
        desc_parts.append(f"Reading Level: {row.reading_level}")
    desc_parts.append(f"Rights: {_rights_text(row.copyrighted)}")
    desc_parts.append(f"Downloads: {row.downloads}")
    return "\n\n".join(desc_parts)


def _opds_bookshelf_subject_metadata(
    bookshelves: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    subject_objs = []
    for b in bookshelves:
        name = b.get("bookshelf")
        shelf_id = b.get("id")
        if not name or shelf_id is None:
            continue
        subject_objs.append({
            "name": name.removeprefix(BOOKSHELF_CATEGORY_PREFIX),
            "scheme": SCHEME_GUTENBERG_BOOKSHELF,
            "code": str(shelf_id),
            "links": [
                {
                    "href": _catalog_url(f"/opds/bookshelves?id={shelf_id}"),
                    "type": _OPDS_FEED_TYPE,
                }
            ],
        })
    return subject_objs


def _opds_subject_metadata(
    raw_subjects: List[Dict[str, Any]], locc_codes: List[str]
) -> List[Dict[str, Any]]:
    subject_objs = []
    for s in raw_subjects:
        if not s.get("subject"):
            continue
        subj = {"name": s["subject"]}
        if s.get("id") is not None:
            subj["scheme"] = SCHEME_GUTENBERG_SUBJECT
            subj["code"] = str(s["id"])
            subj["links"] = [
                {
                    "href": _catalog_url(f"/opds/subjects?id={s['id']}"),
                    "type": _OPDS_FEED_TYPE,
                }
            ]
        subject_objs.append(subj)
    for code in locc_codes:
        main_class = code[0].upper() if code else ""
        label = _LOCC_LABELS.get(main_class, "")
        name = f"{label}: {code}" if label else code
        subject_objs.append({
            "name": name,
            "sortAs": code,
            "scheme": SCHEME_LCC,
            "code": code,
            "links": [
                {
                    "href": _catalog_url(f"/opds/search?locc={code}"),
                    "type": _OPDS_FEED_TYPE,
                }
            ],
        })
    return subject_objs


def _opds_self_link(book_id) -> Dict[str, str]:
    return {
        "rel": "self",
        "href": _catalog_url(f"/opds/publications?id={book_id}"),
        "type": _OPDS_PUBLICATION_TYPE,
    }


def _opds_acquisition_links(
    formats: List[Dict[str, Any]], book_id
) -> List[Dict[str, Any]]:
    """First materialized file (epub3.images only), else the book page."""
    for f in formats:
        fn = f.get("filename")
        if not fn:
            continue
        mtype = (f.get("mediatype") or "").strip()
        link = {
            "rel": _OPDS_ACQUISITION_REL,
            "href": _gutenberg_url(fn),
            "type": mtype or "application/epub+zip",
        }
        if f.get("extent") is not None and f["extent"] > 0:
            link["length"] = f["extent"]
        if f.get("hr_filetype"):
            link["title"] = f["hr_filetype"]
        return [link]
    return [{
        "rel": _OPDS_ACQUISITION_REL,
        "href": _gutenberg_url(f"/ebooks/{book_id}"),
        "type": "text/html",
    }]


def _opds_also_link(book_id) -> Dict[str, str]:
    return {
        "rel": "related",
        "href": _catalog_url(f"/opds/also?id={book_id}"),
        "type": _OPDS_FEED_TYPE,
        "title": "Readers also downloaded",
    }


def _opds_cover_images(book_id, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cover links for books that have a generated epub (and therefore covers)."""
    if not formats:
        return []
    return [
        {
            "href": _gutenberg_url(f"/cache/epub/{book_id}/pg{book_id}.cover.{size}.jpg"),
            "type": "image/jpeg",
            "width": width,
            "height": height,
            "rel": rel,
        }
        for size, width, height, rel in _COVER_SPECS
    ]


# =============================================================================
# Crosswalks
# =============================================================================


@format_dict_result
def crosswalk_opds_small(row) -> Dict[str, Any]:
    """Compact OPDS publication for catalog/search/browse lists."""
    publication_metadata = _opds_book_metadata(row)
    _set_publication_contributors(publication_metadata, _build_creators_slim(row))

    formats = _build_formats(row)
    links = [_opds_self_link(row.book_id)]
    links.extend(_opds_acquisition_links(formats, row.book_id))

    result = {"metadata": publication_metadata, "links": links}
    images = _opds_cover_images(row.book_id, formats)
    if images:
        result["images"] = images
    return result


@format_dict_result
def crosswalk_opds(row) -> Dict[str, Any]:
    """Full OPDS publication for /opds/publications detail."""
    creators = _build_creators(row)
    formats = _build_formats(row)
    locc_codes = [c for c in (list(row.locc_codes) if row.locc_codes else []) if c]

    publication_metadata = _opds_book_metadata(row)
    publication_metadata["accessibility"] = _opds_accessibility()
    _set_publication_contributors(publication_metadata, creators, with_search_link=True)

    if row.release_date:
        publication_metadata["published"] = row.release_date

    publication_metadata["description"] = _opds_description(row, creators)

    subject_objs = (
        _opds_bookshelf_subject_metadata(_build_bookshelves(row))
        + _opds_subject_metadata(_build_subjects(row), locc_codes)
    )
    if subject_objs:
        publication_metadata["subject"] = subject_objs

    if row.publisher:
        publication_metadata["publisher"] = row.publisher

    links = [_opds_self_link(row.book_id)]
    links.extend(_opds_acquisition_links(formats, row.book_id))
    links.append(_opds_also_link(row.book_id))

    result = {"metadata": publication_metadata, "links": links}
    images = _opds_cover_images(row.book_id, formats)
    if images:
        result["images"] = images
    return result


CROSSWALK_MAP = {
    Crosswalk.OPDS: crosswalk_opds,
    Crosswalk.OPDS_SMALL: crosswalk_opds_small,
}
