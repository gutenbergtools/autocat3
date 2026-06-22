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

# PG-generated cover JPEGs (fixed output sizes from ebookconverter)
_COVER_SPECS = (
    ("cover.medium", 200, 288, "http://opds-spec.org/image"),
    ("cover.small", 66, 95, "http://opds-spec.org/image/thumbnail"),
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
            "role": role or "Author",
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
def crosswalk_opds(row) -> Dict[str, Any]:
    """Transform row to OPDS 2.0 publication format."""
    creators = _build_creators(row)
    raw_subjects = _build_subjects(row)
    bookshelves = _build_bookshelves(row)
    formats = _build_formats(row)
    locc_codes = [c for c in (list(row.locc_codes) if row.locc_codes else []) if c]
    formatter = ContributorFormat(creators)

    metadata = {
        "@type": "http://schema.org/Book",
        "identifier": f"https://www.gutenberg.org/ebooks/{row.book_id}",
        "title": row.title,
        "language": (list(row.lang_codes) if row.lang_codes else ["en"])[0] or "en",
        "accessibility": {
            "hazard": ["none"],
            "accessMode": ["textual"],
            "accessModeSufficient": [["textual"]],
            "feature": ["displayTransformability", "unlocked"],
        },
    }

    authors = [c for c in creators if c.get("role", "").lower() in ("author", "aut", "creator", "cre", "")]
    if authors and authors[0].get("name"):
        p = authors[0]
        author = {"name": p["name"], "sortAs": p["name"]}
        if p.get("id"):
            author["identifier"] = f"https://www.gutenberg.org/ebooks/author/{p['id']}"
            author["links"] = [{"href": f"/opds/search?author_id={p['id']}", "type": "application/opds+json"}]
        metadata["author"] = author

    if row.release_date:
        metadata["published"] = row.release_date

    desc_parts = []
    if creators:
        desc_parts.append(f"Creators: {formatter(all=True, strunk_join=True, pretty=True, dates=True, show_role=True)}")
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

    if desc_parts:
        metadata["description"] = "<p>" + "</p><p>".join(html.escape(p) for p in desc_parts) + "</p>"

    subject_objs = []
    for s in raw_subjects:
        if s.get("subject"):
            subj = {"name": s["subject"]}
            if s.get("id") is not None:
                subj["scheme"] = SCHEME_GUTENBERG_SUBJECT
                subj["code"] = str(s["id"])
                subj["links"] = [{"href": f"/opds/subjects?id={s['id']}", "type": "application/opds+json"}]
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
            "links": [{"href": f"/opds/loccs?parent={code}", "type": "application/opds+json"}],
        })
    if subject_objs:
        metadata["subject"] = subject_objs

    if row.publisher:
        metadata["publisher"] = row.publisher

    links = [{
        "rel": "self",
        "href": f"/opds/publications?id={row.book_id}",
        "type": "application/opds-publication+json",
    }]
    target_format = "epub3.images"
    fallback_formats = ["epub.images", "epub.noimages", "kindle.images", "pdf.images", "pdf.noimages", "html"]
    has_acquisition = False

    for try_format in [target_format] + fallback_formats:
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
            links.append(link)
            has_acquisition = True
            break
        if has_acquisition:
            break

    if not has_acquisition:
        links.append({
            "rel": "http://opds-spec.org/acquisition/open-access",
            "href": f"https://www.gutenberg.org/ebooks/{row.book_id}",
            "type": "text/html",
        })

    for b in bookshelves:
        name = b.get("bookshelf")
        shelf_id = b.get("id")
        if not name or shelf_id is None:
            continue
        display_name = name
        if display_name.startswith(BOOKSHELF_CATEGORY_PREFIX):
            display_name = display_name[len(BOOKSHELF_CATEGORY_PREFIX):]
        links.append({
            "rel": "related",
            "href": f"/opds/bookshelves?id={shelf_id}",
            "type": "application/opds+json",
            "title": f"In {display_name}…",
        })

    result = {"metadata": metadata, "links": links}

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
    if images:
        result["images"] = images

    return result


CROSSWALK_MAP = {
    Crosswalk.PG: crosswalk_pg,
    Crosswalk.OPDS: crosswalk_opds,
}
