"""
crosswalks.py — Zachary Rosario

Row-to-dict transforms for PG and OPDS 2.0 output formats.
"""

import html
from typing import Any, Dict, List, Optional
from itertools import zip_longest

from .constants import BOOKSHELF_CATEGORY_PREFIX, Crosswalk, Language, LoCCMainClass
from .formatters import format_dict_result, ContributorFormat

_LOCC_LABELS = {item.code: item.label for item in LoCCMainClass}

LANGUAGE_LABELS = {lang.code: lang.label for lang in Language}

# Readium Web Publication Manifest subject schemes
SCHEME_LCC = "http://purl.org/dc/terms/LCC"
SCHEME_GUTENBERG_SUBJECT = "https://www.gutenberg.org/ebooks/subject/"
SCHEME_GUTENBERG_BOOKSHELF = "https://www.gutenberg.org/ebooks/bookshelf/"

_OPDS_FEED_TYPE = "application/opds+json"
_OPDS_PUBLICATION_TYPE = "application/opds-publication+json"

# PG-generated cover JPEGs (fixed output sizes from ebookconverter)
_COVER_SPECS = (
    ("cover.medium", 200, 288, "http://opds-spec.org/image"),
    ("cover.small", 66, 95, "http://opds-spec.org/image/thumbnail"),
)
_ACQUISITION_FORMATS = (
    "epub3.images",
    "epub.images",
    "epub.noimages",
    "kindle.images",
    "pdf.images",
    "pdf.noimages",
    "html",
)


def _rights_text(copyrighted: Optional[int]) -> str:
    return (
        "Copyrighted. Read the copyright notice inside this book for details."
        if copyrighted
        else "Public domain in the USA."
    )


def _gutenberg_url(path: str) -> str:
    """Build full Gutenberg URL from a path, preserving absolute URLs."""
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return f"https://www.gutenberg.org/{path.lstrip('/')}"


def _build_creators(row) -> List[Dict[str, Any]]:
    names = list(row.creator_names) if row.creator_names else []
    roles = list(row.creator_roles) if row.creator_roles else []
    ids = list(row.creator_ids) if row.creator_ids else []
    born_floors = list(row.creator_born_floor) if row.creator_born_floor else []
    born_ceils = list(row.creator_born_ceil) if row.creator_born_ceil else []
    died_floors = list(row.creator_died_floor) if row.creator_died_floor else []
    died_ceils = list(row.creator_died_ceil) if row.creator_died_ceil else []
    creators = []
    for name, role, cid, bf, bc, df, dc in zip_longest(
        names, roles, ids, born_floors, born_ceils, died_floors, died_ceils, fillvalue=None
    ):
        if not name:
            continue
        creators.append({
            "id": cid,
            "name": name,
            "role": role,
            "born_floor": bf,
            "born_ceil": bc,
            "died_floor": df,
            "died_ceil": dc,
        })
    return creators


def _build_subjects(row) -> List[Dict[str, Any]]:
    names = list(row.subject_names) if row.subject_names else []
    ids = list(row.subject_ids) if row.subject_ids else []
    return [
        {"id": sid, "subject": name}
        for name, sid in zip_longest(names, ids, fillvalue=None)
        if name
    ]


def _build_bookshelves(row) -> List[Dict[str, Any]]:
    names = list(row.bookshelf_names) if row.bookshelf_names else []
    ids = list(row.bookshelf_ids) if row.bookshelf_ids else []
    return [
        {"id": bid, "bookshelf": name}
        for name, bid in zip_longest(names, ids, fillvalue=None)
        if name
    ]


def _build_cover_formats(row) -> List[Dict[str, Any]]:
    filenames = list(row.format_filenames) if row.format_filenames else []
    filetypes = list(row.format_filetypes) if row.format_filetypes else []
    mediatypes = list(row.format_mediatypes) if row.format_mediatypes else []
    return [
        {"filename": fn, "filetype": ftype, "mediatype": med}
        for fn, ftype, med in zip_longest(filenames, filetypes, mediatypes, fillvalue=None)
        if fn
    ]


def _build_creators_slim(row) -> List[Dict[str, Any]]:
    names = list(row.creator_names) if row.creator_names else []
    roles = list(row.creator_roles) if row.creator_roles else []
    ids = list(row.creator_ids) if row.creator_ids else []
    return [
        {"id": cid, "name": name, "role": role}
        for name, role, cid in zip_longest(names, roles, ids, fillvalue=None)
        if name
    ]


def _build_formats(row) -> List[Dict[str, Any]]:
    filenames = list(row.format_filenames) if row.format_filenames else []
    filetypes = list(row.format_filetypes) if row.format_filetypes else []
    hr_filetypes = list(row.format_hr_filetypes) if row.format_hr_filetypes else []
    mediatypes = list(row.format_mediatypes) if row.format_mediatypes else []
    extents = list(row.format_extents) if row.format_extents else []
    results = []
    for fn, ftype, hr, med, extent in zip_longest(
        filenames, filetypes, hr_filetypes, mediatypes, extents, fillvalue=None
    ):
        if not fn:
            continue
        results.append({
            "filename": fn,
            "filetype": ftype,
            "hr_filetype": hr,
            "mediatype": med,
            "extent": extent,
        })
    return results


def _opds_book_metadata(row) -> Dict[str, Any]:
    return {
        "@type": "http://schema.org/Book",
        "identifier": f"https://www.gutenberg.org/ebooks/{row.book_id}",
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
    """Map a mv_books_dc creator_roles label to a WPM metadata field."""
    if not role:
        return "contributor"
    return _OPDS_ROLE_FIELDS.get(role.strip().lower(), "contributor")


def _build_opds_contributor_entry(
    person: Dict[str, Any], *, with_search_link: bool = False
) -> Dict[str, Any]:
    contributor = {"name": person["name"], "sortAs": person["name"]}
    if with_search_link and person.get("id"):
        contributor["identifier"] = (
            f"https://www.gutenberg.org/ebooks/author/{person['id']}"
        )
        contributor["links"] = [
            {"href": f"/opds/search?author_id={person['id']}", "type": _OPDS_FEED_TYPE}
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


def _opds_description(row, creators, formatter: ContributorFormat) -> Optional[str]:
    desc_parts = []
    if creators:
        desc_parts.append(
            f"Creators: {formatter(all=True, strunk_join=True, pretty=True, dates=True, show_role=True)}"
        )
    summary = (list(row.summary) if row.summary else [None])[0]
    if summary:
        desc_parts.append(summary)
    credits = (list(row.credits) if row.credits else [None])[0]
    if credits:
        desc_parts.append(f"Credits: {credits}")
    if row.reading_level:
        desc_parts.append(f"Reading Level: {row.reading_level}")
    dcmitype = [t for t in (list(row.dcmitypes) if row.dcmitypes else []) if t]
    if dcmitype:
        desc_parts.append(f"Category: {', '.join(dcmitype)}")
    desc_parts.append(f"Rights: {_rights_text(row.copyrighted)}")
    desc_parts.append(f"Downloads: {row.downloads}")
    if not desc_parts:
        return None
    return "<p>" + "</p><p>".join(html.escape(p) for p in desc_parts) + "</p>"


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
                {"href": f"/opds/bookshelves?id={shelf_id}", "type": _OPDS_FEED_TYPE}
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
                {"href": f"/opds/subjects?id={s['id']}", "type": _OPDS_FEED_TYPE}
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
            "links": [{"href": f"/opds/search?locc={code}", "type": _OPDS_FEED_TYPE}],
        })
    return subject_objs


def _opds_self_link(book_id) -> Dict[str, str]:
    return {
        "rel": "self",
        "href": f"/opds/publications?id={book_id}",
        "type": _OPDS_PUBLICATION_TYPE,
    }


def _opds_acquisition_links(
    formats: List[Dict[str, Any]], book_id
) -> List[Dict[str, Any]]:
    for try_format in _ACQUISITION_FORMATS:
        for f in formats:
            fn = f.get("filename")
            if not fn:
                continue
            ftype = (f.get("filetype") or "").strip().lower()
            if ftype != try_format:
                continue
            mtype = (f.get("mediatype") or "").strip()
            link = {
                "rel": "http://opds-spec.org/acquisition/open-access",
                "href": _gutenberg_url(fn),
                "type": mtype or "application/epub+zip",
            }
            if f.get("extent") is not None and f["extent"] > 0:
                link["length"] = f["extent"]
            if f.get("hr_filetype"):
                link["title"] = f["hr_filetype"]
            return [link]
    return [{
        "rel": "http://opds-spec.org/acquisition/open-access",
        "href": f"https://www.gutenberg.org/ebooks/{book_id}",
        "type": "text/html",
    }]


def _opds_also_link(book_id) -> Dict[str, str]:
    return {
        "rel": "related",
        "href": f"/opds/also?id={book_id}",
        "type": _OPDS_FEED_TYPE,
        "title": "Readers also downloaded",
    }


def _opds_cover_images(formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formats_by_type = {
        (f.get("filetype") or "").strip(): f
        for f in formats
        if f.get("filename") and (f.get("filetype") or "").strip()
    }
    images = []
    for filetype, width, height, rel in _COVER_SPECS:
        f = formats_by_type.get(filetype)
        if not f:
            continue
        mtype = (f.get("mediatype") or "").strip() or "image/jpeg"
        images.append({
            "href": _gutenberg_url(f["filename"]),
            "type": mtype,
            "width": width,
            "height": height,
            "rel": rel,
        })
    return images


def _opds_row_parts(row):
    """Shared row parsing for OPDS crosswalks."""
    creators = _build_creators(row)
    formats = _build_formats(row)
    return {
        "creators": creators,
        "formats": formats,
        "raw_subjects": _build_subjects(row),
        "bookshelves": _build_bookshelves(row),
        "locc_codes": [c for c in (list(row.locc_codes) if row.locc_codes else []) if c],
        "formatter": ContributorFormat(creators),
    }


@format_dict_result
def crosswalk_pg(row) -> Dict[str, Any]:
    creators = _build_creators(row)
    subjects = [s["subject"] for s in _build_subjects(row) if s.get("subject")]
    bookshelves = [b["bookshelf"] for b in _build_bookshelves(row) if b.get("bookshelf")]
    language = [
        {"code": code, "name": LANGUAGE_LABELS.get(code, code)}
        for code in (list(row.lang_codes) if row.lang_codes else [])
        if code
    ]
    formats = _build_formats(row)

    formatter = ContributorFormat(creators)

    return {
        "ebook_no": row.book_id,
        "title": row.title,
        "contributors": creators,
        "language": language,
        "subjects": subjects,
        "bookshelves": bookshelves,
        "release_date": row.release_date,
        "downloads_last_30_days": row.downloads,
        "files": [
            {"filename": f.get("filename"), "type": f.get("mediatype"), "size": f.get("extent")}
            for f in formats if f.get("filename")
        ],
        "cover_url": (list(row.coverpage) if row.coverpage else [None])[0],
        "format": formatter,
    }


@format_dict_result
def crosswalk_opds_small(row) -> Dict[str, Any]:
    """Compact OPDS publication for catalog/search/browse lists."""
    publication_metadata = _opds_book_metadata(row)
    _set_publication_contributors(publication_metadata, _build_creators_slim(row))

    links = [_opds_self_link(row.book_id)]
    links.extend(_opds_acquisition_links(_build_formats(row), row.book_id))

    result = {
        "metadata": publication_metadata,
        "links": links,
    }
    images = _opds_cover_images(_build_cover_formats(row))
    if images:
        result["images"] = images
    return result


@format_dict_result
def crosswalk_opds(row) -> Dict[str, Any]:
    """Full OPDS publication for /opds/publications detail."""
    parts = _opds_row_parts(row)
    publication_metadata = _opds_book_metadata(row)
    publication_metadata["accessibility"] = _opds_accessibility()

    _set_publication_contributors(
        publication_metadata, parts["creators"], with_search_link=True
    )

    if row.release_date:
        publication_metadata["published"] = row.release_date

    description = _opds_description(row, parts["creators"], parts["formatter"])
    if description:
        publication_metadata["description"] = description

    subject_objs = (
        _opds_bookshelf_subject_metadata(parts["bookshelves"])
        + _opds_subject_metadata(parts["raw_subjects"], parts["locc_codes"])
    )
    if subject_objs:
        publication_metadata["subject"] = subject_objs

    if row.publisher:
        publication_metadata["publisher"] = row.publisher

    links = [_opds_self_link(row.book_id)]
    links.extend(_opds_acquisition_links(parts["formats"], row.book_id))
    links.append(_opds_also_link(row.book_id))

    result = {"metadata": publication_metadata, "links": links}
    images = _opds_cover_images(parts["formats"])
    if images:
        result["images"] = images

    return result


CROSSWALK_MAP = {
    Crosswalk.PG: crosswalk_pg,
    Crosswalk.OPDS: crosswalk_opds,
    Crosswalk.OPDS_SMALL: crosswalk_opds_small,
}
