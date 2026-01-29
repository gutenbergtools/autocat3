"""
Formatting helpers based on libgutenberg.DublinCore.
https://github.com/gutenbergtools/libgutenberg/blob/master/libgutenberg/DublinCore.py
"""

import re
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

_RE_MARC_SUBFIELD = re.compile(r"\$[a-z]")
_RE_MARC_SPSEP = re.compile(r"[\n ](,|:)([A-Za-z0-9])")
_RE_CURLY_SINGLE = re.compile("[\u2018\u2019]")  # ' '
_RE_CURLY_DOUBLE = re.compile("[\u201c\u201d]")  # " "
_RE_TITLE_SPLITTER = re.compile(r"\s*[;:]\s*")
_RE_PARENS = re.compile(r"\(.*\)")
_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_UPDATED = re.compile(r"\s*[Uu]pdated?:\s*.*$")  # Strip "Updated:" and everything after

_FIELDS_TO_FORMAT = frozenset({
    "title",        # Book title
    "name",         # Contributor names (from authors table)
    "publisher",    # MARC 260/264
    "summary",      # MARC 520
    "credits",      # MARC 508
    "reading_level",# MARC 908
    "subject",      # Individual subject string
    "subjects",     # List of subjects (parent key)
    "bookshelf",    # Individual bookshelf string
    "bookshelves",  # List of bookshelves (parent key)
})


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


def strip_updated(text: str) -> str:
    """Strip 'Updated:' and everything after from credits (MARC 508)."""
    if not text or not isinstance(text, str):
        return ""
    return _RE_UPDATED.sub("", text).strip()


def format_field(key: str, value: str, fields: frozenset = _FIELDS_TO_FORMAT) -> str:
    """Format a single field value."""
    if not value or not isinstance(value, str):
        return ""
    if key in fields:
        value = strip_marc_subfields(value)
        value = normalize_text(value)
    # Credits field: strip "Updated:" and everything after
    if key == "credits":
        value = strip_updated(value)
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


def format_list(parent_key: str, lst: List, fields: frozenset = _FIELDS_TO_FORMAT) -> List:
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


def format_dict_result(fn: Optional[Callable] = None, *, fields_to_format: frozenset = _FIELDS_TO_FORMAT) -> Callable:
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


def strunk(items: List[str]) -> str:
    """
    Join list with Oxford comma: ["Tom", "Dick", "Harry"] -> "Tom, Dick, and Harry"
    """
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _format_date_range(floor: Optional[int], ceil: Optional[int]) -> str:
    """Format birth/death date with uncertainty."""
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
    """Reverse 'Twain, Mark' -> 'Mark Twain'."""
    if not name:
        return ""
    rev = " ".join(reversed(name.split(", ")))
    rev = _RE_PARENS.sub("", rev)
    rev = _RE_MULTI_SPACE.sub(" ", rev)
    return rev.strip()


def format_contributor(
    name: str,
    role: Optional[str] = None,
    born_floor: Optional[int] = None,
    born_ceil: Optional[int] = None,
    died_floor: Optional[int] = None,
    died_ceil: Optional[int] = None,
    *,
    pretty: bool = False,
    dates: bool = True,
    show_role: bool = True,
) -> str:
    """
    Centralized contributor formatting with options.

    Args:
        name: Contributor name (e.g. "Twain, Mark")
        role: Role (e.g. "Author", "Editor")
        born_floor/ceil: Birth date range
        died_floor/ceil: Death date range
        pretty: If True, reverse name to "Mark Twain" style
        dates: If True, include birth-death dates
        show_role: If True, show role in brackets (if not Author/Creator)

    Examples:
        format_contributor("Twain, Mark", "Author", 1835, 1835, 1910, 1910)
            -> "Twain, Mark, 1835-1910"

        format_contributor("Twain, Mark", "Editor", 1835, 1835, 1910, 1910, show_role=True)
            -> "Twain, Mark, 1835-1910 [Editor]"

        format_contributor("Twain, Mark", "Author", 1835, 1835, 1910, 1910, pretty=True)
            -> "Mark Twain (1835-1910)"

        format_contributor("Twain, Mark", "Editor", pretty=True, dates=False, show_role=True)
            -> "Mark Twain [Editor]"
    """
    if not name:
        return ""

    # Name formatting
    display_name = _reverse_name(name) if pretty else name

    # Date formatting
    date_str = ""
    if dates:
        born = _format_date_range(born_floor, born_ceil)
        died = _format_date_range(died_floor, died_ceil)
        if born and died:
            date_str = f"{born}-{died}"
        elif born:
            date_str = f"{born}-"
        elif died:
            date_str = f"d. {died}"

    # Role formatting (skip if Author/Creator)
    role_str = ""
    if show_role and role and role.lower() not in ("author", "creator", "aut", "cre"):
        role_str = role

    # Combine based on style
    if pretty:
        # Pretty style: "Mark Twain (1835-1910) [Editor]"
        result = display_name
        if date_str:
            result += f" ({date_str})"
        if role_str:
            result += f" [{role_str}]"
    else:
        # Formal style: "Twain, Mark, 1835-1910 [Editor]"
        result = display_name
        if date_str:
            result += f", {date_str}"
        if role_str:
            result += f" [{role_str}]"

    return result


def format_contributor_dict(contributor: Dict, **kwargs) -> str:
    return format_contributor(
        name=contributor.get("name", ""),
        role=contributor.get("role"),
        born_floor=contributor.get("born_floor"),
        born_ceil=contributor.get("born_ceil"),
        died_floor=contributor.get("died_floor"),
        died_ceil=contributor.get("died_ceil"),
        **kwargs,
    )


class ContributorFormat:
    """
    Simple wrapper to format contributors.

    Usage:
        fmt = book["format"]
        fmt()                              # main author: "Twain, Mark, 1835-1910"
        fmt(pretty=True)                   # main author: "Mark Twain (1835-1910)"
        fmt(all=True)                      # all: "Twain, Mark, 1835-1910; Doe, Jane [Editor]"
        fmt(all=True, pretty=True)         # all: "Mark Twain (1835-1910); Jane Doe [Editor]"
        fmt(all=True, strunk=True)         # all: "Mark Twain, Jane Doe, and John Smith"
    """

    def __init__(self, contributors: List[Dict]):
        self._c = contributors

    def __call__(
        self,
        *,
        all: bool = False,
        sep: str = "; ",
        strunk_join: bool = False,
        pretty: bool = False,
        dates: bool = True,
        show_role: bool = True,
    ) -> str:
        """
        Format contributor(s).

        Args:
            all: If True, format all contributors. If False (default), just main/first.
            sep: Separator when all=True and strunk_join=False (default "; ")
            strunk_join: If True, use Oxford comma "and" style instead of sep
            pretty: "Mark Twain" style vs "Twain, Mark" formal
            dates: Include birth-death dates
            show_role: Show role in brackets (if not Author)
        """
        if all:
            formatted = [
                format_contributor_dict(c, pretty=pretty, dates=dates, show_role=show_role)
                for c in self._c if c.get("name")
            ]
            if strunk_join:
                return strunk(formatted)
            return sep.join(formatted)
        # Main/first author only
        if self._c:
            return format_contributor_dict(self._c[0], pretty=pretty, dates=dates, show_role=show_role)
        return ""
