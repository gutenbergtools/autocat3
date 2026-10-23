"""
constants.py — Zachary Rosario

Enums and constants for the OPDS catalog data layer.
"""

from enum import Enum
from typing import Tuple

__all__ = [
    "SearchField",
    "OrderBy",
    "SortDirection",
    "Crosswalk",
    "CuratedBookshelves",
    "BOOKSHELF_CATEGORY_PREFIX",
]

# Curated shelves live in the `bookshelves` table as "Category: <label>" rows.
BOOKSHELF_CATEGORY_PREFIX = "Category: "


class SearchField(str, Enum):
    BOOK = "book"
    TITLE = "title"
    AUTHOR = "author"


class OrderBy(str, Enum):
    """Sort options."""

    RELEVANCE = "relevance"
    DOWNLOADS = "downloads"
    TITLE = "title"
    AUTHOR = "author"
    RELEASE_DATE = "release_date"
    FILEMTIME = "filemtime"
    RANDOM = "random"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class Crosswalk(str, Enum):
    OPDS = "opds"
    OPDS_SMALL = "opds_small"


class CuratedBookshelves(Enum):
    """Curated groupings of Project Gutenberg "Category: ..." bookshelves.

    Each shelf is (bookshelves.pk, display label). The primary keys are
    stable for this catalog, so navigation does not look them up on load.
    """

    LITERATURE = (
        "Literature",
        (
            (644, "Adventure"),
            (654, "American Literature"),
            (653, "British Literature"),
            (652, "French Literature"),
            (651, "German Literature"),
            (650, "Russian Literature"),
            (649, "Classics of Literature"),
            (643, "Biographies"),
            (645, "Novels"),
            (634, "Short Stories"),
            (637, "Poetry"),
            (642, "Plays/Films/Dramas"),
            (639, "Romance"),
            (638, "Science-Fiction & Fantasy"),
            (640, "Crime, Thrillers and Mystery"),
            (646, "Mythology, Legends & Folklore"),
            (641, "Humour"),
            (636, "Children & Young Adult Reading"),
            (633, "Literature - Other"),
        ),
    )
    SCIENCE_TECHNOLOGY = (
        "Science & Technology",
        (
            (671, "Engineering & Technology"),
            (672, "Mathematics"),
            (667, "Science - Physics"),
            (668, "Science - Chemistry/Biochemistry"),
            (669, "Science - Biology"),
            (670, "Science - Earth/Agricultural/Farming"),
            (673, "Research Methods/Statistics/Information Sys"),
            (685, "Environmental Issues"),
        ),
    )
    HISTORY = (
        "History",
        (
            (656, "History - American"),
            (657, "History - British"),
            (658, "History - European"),
            (659, "History - Ancient"),
            (660, "History - Medieval/Middle Ages"),
            (661, "History - Early Modern (c. 1450-1750)"),
            (662, "History - Modern (1750+)"),
            (663, "History - Religious"),
            (664, "History - Royalty"),
            (665, "History - Warfare"),
            (666, "History - Schools & Universities"),
            (655, "History - Other"),
            (686, "Archaeology & Anthropology"),
        ),
    )
    SOCIAL_SCIENCES_SOCIETY = (
        "Social Sciences & Society",
        (
            (695, "Business/Management"),
            (696, "Economics"),
            (689, "Law & Criminology"),
            (690, "Gender & Sexuality Studies"),
            (688, "Psychiatry/Psychology"),
            (693, "Sociology"),
            (694, "Politics"),
            (701, "Parenthood & Family Relations"),
            (700, "Old Age & the Elderly"),
        ),
    )
    ARTS_CULTURE = (
        "Arts & Culture",
        (
            (675, "Art"),
            (674, "Architecture"),
            (677, "Music"),
            (676, "Fashion"),
            (698, "Journalism/Media/Writing"),
            (687, "Language & Communication"),
            (647, "Essays, Letters & Speeches"),
        ),
    )
    RELIGION_PHILOSOPHY = (
        "Religion & Philosophy",
        (
            (692, "Religion/Spirituality"),
            (691, "Philosophy & Ethics"),
        ),
    )
    LIFESTYLE_HOBBIES = (
        "Lifestyle & Hobbies",
        (
            (678, "Cooking & Drinking"),
            (680, "Sports/Hobbies"),
            (679, "How To ..."),
            (648, "Travel Writing"),
            (683, "Nature/Gardening/Animals"),
            (703, "Sexuality & Erotica"),
        ),
    )
    HEALTH_MEDICINE = (
        "Health & Medicine",
        (
            (681, "Health & Medicine"),
            (682, "Drugs/Alcohol/Pharmacology"),
            (684, "Nutrition"),
        ),
    )
    EDUCATION_REFERENCE = (
        "Education & Reference",
        (
            (697, "Encyclopedias/Dictionaries/Reference"),
            (704, "Teaching & Education"),
            (702, "Reports & Conference Proceedings"),
            (699, "Journals"),
        ),
    )

    @property
    def genre(self) -> str:
        return self.value[0]

    @property
    def shelves(self) -> Tuple[Tuple[int, str], ...]:
        """(bookshelves.pk, display label) pairs."""
        return self.value[1]

    @property
    def shelf_names(self) -> Tuple[str, ...]:
        """Display labels for this category's shelves."""
        return tuple(name for _, name in self.shelves)
