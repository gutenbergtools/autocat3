import html
import re
from typing import Any, Dict, List, Optional
from itertools import zip_longest

from .constants import Crosswalk, Language
from .formatters import format_dict_result, ContributorFormat, format_contributor_dict

LANGUAGE_LABELS = {lang.code: lang.label for lang in Language}


def _estimate_mp3_duration(file_size_bytes: int, bitrate_kbps: int = 128) -> int:
    """Estimate MP3 duration from file size assuming CBR encoding.
    
    LibriVox standard: 128kbps CBR, 44.1kHz, mono.
    Formula: duration = file_size_bytes * 8 / bitrate_bps
    """
    if not file_size_bytes or file_size_bytes <= 0:
        return 0
    return int(file_size_bytes * 8 / (bitrate_kbps * 1000))


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
    """Transform row to OPDS 2.0 / Readium Audiobook Profile format."""
    creators = _build_creators(row)
    subjects = [s["subject"] for s in _build_subjects(row) if s.get("subject")]
    bookshelves = _build_bookshelves(row)
    formats = _build_formats(row)
    locc_codes = [c for c in (list(row.locc_codes) if row.locc_codes else []) if c]
    formatter = ContributorFormat(creators)
    is_audio = row.is_audio

    metadata = {
        "@type": "http://schema.org/Audiobook" if is_audio else "http://schema.org/Book",
        "identifier": f"urn:gutenberg:{row.book_id}",
        "title": row.title,
        "language": (list(row.lang_codes) if row.lang_codes else ["en"])[0] or "en",
    }

    if is_audio:
        metadata["conformsTo"] = "https://readium.org/webpub-manifest/profiles/audiobook"

    # Accessibility metadata (W3C/schema.org)
    accessibility = {
        "hazard": ["none"],
    }
    if is_audio:
        accessibility["conformsTo"] = ["https://readium.org/webpub-manifest/profiles/audiobook"]
        accessibility["accessMode"] = ["auditory"]
        accessibility["accessModeSufficient"] = [["auditory"]]
        accessibility["feature"] = ["unlocked"]
    else:
        accessibility["accessMode"] = ["textual"]
        accessibility["accessModeSufficient"] = [["textual"]]
        accessibility["feature"] = ["displayTransformability", "unlocked"]
    metadata["accessibility"] = accessibility

    authors = [c for c in creators if c.get("role", "").lower() in ("author", "aut", "creator", "cre", "")]
    if authors and authors[0].get("name"):
        p = authors[0]
        author = {"name": p["name"], "sortAs": p["name"]}
        if p.get("id"):
            author["identifier"] = f"https://www.gutenberg.org/ebooks/author/{p['id']}"
        metadata["author"] = author

    if is_audio:
        narrator_roles = ("narrator", "nrt", "reader", "prf", "spk", "sng", "performer", "speaker", "singer")
        narrators = [c for c in creators if c.get("role", "").lower() in narrator_roles]
        if narrators:
            narrator_fmt = ContributorFormat(narrators)
            metadata["narrator"] = narrator_fmt(all=True, pretty=True, dates=False, show_role=False).split("; ")

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

    subjects += locc_codes
    if subjects:
        metadata["subject"] = subjects

    if row.publisher:
        metadata["publisher"] = row.publisher

    collections = []
    for b in bookshelves:
        if b.get("bookshelf"):
            collections.append({
                "name": b["bookshelf"],
                "identifier": f"https://www.gutenberg.org/ebooks/bookshelf/{b.get('id', '')}",
            })
    for code in locc_codes:
        collections.append({
            "name": code,
            "identifier": f"https://www.gutenberg.org/ebooks/locc/{code}",
        })
    if collections:
        metadata["belongsTo"] = {"collection": collections}

    links = []
    reading_order = []

    if is_audio:
        total_duration = 0
        for f in formats:
            fn = f.get("filename")
            ftype = (f.get("filetype") or "").strip().lower()
            if not fn or ftype != "mp3":
                continue

            href = _gutenberg_url(fn)
            track = {
                "href": href,
                "type": "audio/mpeg",
                "bitrate": 128,  # LibriVox standard: 128kbps CBR
            }

            file_size = f.get("extent")
            if file_size and file_size > 0:
                duration = _estimate_mp3_duration(file_size)
                track["duration"] = duration
                total_duration += duration

            match = re.search(r'-(\d+)\.mp3$', fn, re.IGNORECASE)
            if match:
                track["title"] = f"Part {match.group(1)}"

            reading_order.append(track)

        reading_order.sort(key=lambda t: t.get("title", ""))

        if total_duration > 0:
            metadata["duration"] = total_duration

        links.append({
            "rel": "self",
            "href": f"https://www.gutenberg.org/ebooks/{row.book_id}.audiobook",
            "type": "application/audiobook+json",
        })

        has_zip = False
        for f in formats:
            fn = f.get("filename") or ""
            if fn.endswith("-mp3.zip") or fn.endswith("_mp3.zip"):
                links.append({
                    "rel": "http://opds-spec.org/acquisition/open-access",
                    "href": _gutenberg_url(fn),
                    "type": "application/zip",
                    "title": "Download all MP3s (ZIP)",
                    **({"length": f["extent"]} if f.get("extent") and f["extent"] > 0 else {}),
                })
                has_zip = True
                break

        if not has_zip:
            # No ZIP available - fall back to HTML page
            links.append({
                "rel": "http://opds-spec.org/acquisition/open-access",
                "href": f"https://www.gutenberg.org/ebooks/{row.book_id}",
                "type": "text/html",
            })
    else:
        target_format = "epub3.images"
        fallback_formats = ["epub.images", "epub.noimages", "kindle.images", "pdf.images", "pdf.noimages", "html"]

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
                break
            if links:
                break

    if not links:
        links.append({
            "rel": "http://opds-spec.org/acquisition/open-access",
            "href": f"https://www.gutenberg.org/ebooks/{row.book_id}",
            "type": "text/html",
        })

    if is_audio:
        result = {
            "@context": "http://readium.org/webpub-manifest/context.jsonld",
            "metadata": metadata,
            "links": links,
        }
    else:
        result = {"metadata": metadata, "links": links}

    if reading_order:
        result["readingOrder"] = reading_order

    images = []
    for f in formats:
        ft = f.get("filetype") or ""
        fn = f.get("filename")
        if fn and ("cover.medium" in ft or ("cover" in ft and not images)):
            images.append({"href": _gutenberg_url(fn), "type": "image/jpeg"})
            if "cover.medium" in ft:
                break
    if images:
        result["images"] = images  # OPDS 2.0
        if is_audio:
            result["resources"] = [{"rel": "cover", **img} for img in images]  # Readium

    return result


CROSSWALK_MAP = {
    Crosswalk.PG: crosswalk_pg,
    Crosswalk.OPDS: crosswalk_opds,
}
