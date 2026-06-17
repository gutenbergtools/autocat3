"""
constants.py — Zachary Rosario

Enums and constants for the mv_books_dc search module.
"""

from enum import Enum
from typing import Tuple

__all__ = [
    "FileType",
    "SearchType",
    "SearchField",
    "OrderBy",
    "SortDirection",
    "Crosswalk",
    "Language",
    "LoCCMainClass",
    "CuratedBookshelves",
    "BOOKSHELF_CATEGORY_PREFIX",
]

# Curated shelves live in the `bookshelves` table as "Category: <label>" rows.
BOOKSHELF_CATEGORY_PREFIX = "Category: "


class FileType(str, Enum):
    EPUB = "application/epub+zip"
    KINDLE = "application/x-mobipocket-ebook"
    PDF = "application/pdf"
    TXT = "text/plain"
    HTML = "text/html"


class SearchType(str, Enum):
    FTS = "fts"
    FUZZY = "fuzzy"
    HYBRID = "hybrid"


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
    RANDOM = "random"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class Crosswalk(str, Enum):
    PG = "pg"
    OPDS = "opds"


class Language(Enum):
    EN = ("en", "English")
    AF = ("af", "Afrikaans")
    ALE = ("ale", "Aleut")
    ANG = ("ang", "Old English")
    AR = ("ar", "Arabic")
    ARP = ("arp", "Arapaho")
    BG = ("bg", "Bulgarian")
    BGS = ("bgs", "Basa Banyumasan")
    BO = ("bo", "Tibetan")
    BR = ("br", "Breton")
    BRX = ("brx", "Bodo")
    CA = ("ca", "Catalan")
    CEB = ("ceb", "Cebuano")
    CS = ("cs", "Czech")
    CSB = ("csb", "Kashubian")
    CY = ("cy", "Welsh")
    DA = ("da", "Danish")
    DE = ("de", "German")
    EL = ("el", "Greek")
    ENM = ("enm", "Middle English")
    EO = ("eo", "Esperanto")
    ES = ("es", "Spanish")
    ET = ("et", "Estonian")
    FA = ("fa", "Persian")
    FI = ("fi", "Finnish")
    FR = ("fr", "French")
    FUR = ("fur", "Friulian")
    FY = ("fy", "Western Frisian")
    GA = ("ga", "Irish")
    GL = ("gl", "Galician")
    GLA = ("gla", "Scottish Gaelic")
    GRC = ("grc", "Ancient Greek")
    HAI = ("hai", "Haida")
    HE = ("he", "Hebrew")
    HU = ("hu", "Hungarian")
    IA = ("ia", "Interlingua")
    ILO = ("ilo", "Iloko")
    IS = ("is", "Icelandic")
    IT = ("it", "Italian")
    IU = ("iu", "Inuktitut")
    JA = ("ja", "Japanese")
    KHA = ("kha", "Khasi")
    KLD = ("kld", "Klamath-Modoc")
    KO = ("ko", "Korean")
    LA = ("la", "Latin")
    LT = ("lt", "Lithuanian")
    MI = ("mi", "Māori")
    MYN = ("myn", "Mayan Languages")
    NAH = ("nah", "Nahuatl")
    NAI = ("nai", "North American Indian")
    NAP = ("nap", "Neapolitan")
    NAV = ("nav", "Navajo")
    NL = ("nl", "Dutch")
    NO = ("no", "Norwegian")
    OC = ("oc", "Occitan")
    OJI = ("oji", "Ojibwa")
    PL = ("pl", "Polish")
    PT = ("pt", "Portuguese")
    RMQ = ("rmq", "Romani")
    RO = ("ro", "Romanian")
    RU = ("ru", "Russian")
    SA = ("sa", "Sanskrit")
    SCO = ("sco", "Scots")
    SL = ("sl", "Slovenian")
    SR = ("sr", "Serbian")
    SV = ("sv", "Swedish")
    TE = ("te", "Telugu")
    TL = ("tl", "Tagalog")
    YI = ("yi", "Yiddish")
    ZH = ("zh", "Chinese")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


class LoCCMainClass(Enum):
    A = ("A", "General Works")
    B = ("B", "Philosophy, Psychology, Religion")
    C = ("C", "History: Auxiliary Sciences")
    D = ("D", "History: General and Eastern Hemisphere")
    E = ("E", "History: America")
    F = ("F", "History: America (Local)")
    G = ("G", "Geography, Anthropology, Recreation")
    H = ("H", "Social Sciences")
    J = ("J", "Political Science")
    K = ("K", "Law")
    L = ("L", "Education")
    M = ("M", "Music")
    N = ("N", "Fine Arts")
    P = ("P", "Language and Literature")
    Q = ("Q", "Science")
    R = ("R", "Medicine")
    S = ("S", "Agriculture")
    T = ("T", "Technology")
    U = ("U", "Military Science")
    V = ("V", "Naval Science")
    Z = ("Z", "Bibliography, Library Science")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


class CuratedBookshelves(Enum):
    """Curated groupings of Project Gutenberg "Category: ..." bookshelves.

    Shelves are referenced by their display label only; the matching
    `bookshelves` row is "Category: <label>" and its primary key is resolved
    from the database on first use (see FullTextSearch.curated_shelves). The
    ids are stable for a given dataset but are not hard-coded here so a
    rebuild can't silently point a label at the wrong shelf.
    """

    LITERATURE = (
        "Literature",
        (
            "Adventure",
            "American Literature",
            "British Literature",
            "French Literature",
            "German Literature",
            "Russian Literature",
            "Classics of Literature",
            "Biographies",
            "Novels",
            "Short Stories",
            "Poetry",
            "Plays/Films/Dramas",
            "Romance",
            "Science-Fiction & Fantasy",
            "Crime, Thrillers and Mystery",
            "Mythology, Legends & Folklore",
            "Humour",
            "Children & Young Adult Reading",
            "Literature - Other",
        ),
    )
    SCIENCE_TECHNOLOGY = (
        "Science & Technology",
        (
            "Engineering & Technology",
            "Mathematics",
            "Science - Physics",
            "Science - Chemistry/Biochemistry",
            "Science - Biology",
            "Science - Earth/Agricultural/Farming",
            "Research Methods/Statistics/Information Sys",
            "Environmental Issues",
        ),
    )
    HISTORY = (
        "History",
        (
            "History - American",
            "History - British",
            "History - European",
            "History - Ancient",
            "History - Medieval/Middle Ages",
            "History - Early Modern (c. 1450-1750)",
            "History - Modern (1750+)",
            "History - Religious",
            "History - Royalty",
            "History - Warfare",
            "History - Schools & Universities",
            "History - Other",
            "Archaeology & Anthropology",
        ),
    )
    SOCIAL_SCIENCES_SOCIETY = (
        "Social Sciences & Society",
        (
            "Business/Management",
            "Economics",
            "Law & Criminology",
            "Gender & Sexuality Studies",
            "Psychiatry/Psychology",
            "Sociology",
            "Politics",
            "Parenthood & Family Relations",
            "Old Age & the Elderly",
        ),
    )
    ARTS_CULTURE = (
        "Arts & Culture",
        (
            "Art",
            "Architecture",
            "Music",
            "Fashion",
            "Journalism/Media/Writing",
            "Language & Communication",
            "Essays, Letters & Speeches",
        ),
    )
    RELIGION_PHILOSOPHY = (
        "Religion & Philosophy",
        (
            "Religion/Spirituality",
            "Philosophy & Ethics",
        ),
    )
    LIFESTYLE_HOBBIES = (
        "Lifestyle & Hobbies",
        (
            "Cooking & Drinking",
            "Sports/Hobbies",
            "How To ...",
            "Travel Writing",
            "Nature/Gardening/Animals",
            "Sexuality & Erotica",
        ),
    )
    HEALTH_MEDICINE = (
        "Health & Medicine",
        (
            "Health & Medicine",
            "Drugs/Alcohol/Pharmacology",
            "Nutrition",
        ),
    )
    EDUCATION_REFERENCE = (
        "Education & Reference",
        (
            "Encyclopedias/Dictionaries/Reference",
            "Teaching & Education",
            "Reports & Conference Proceedings",
            "Journals",
        ),
    )

    @property
    def genre(self) -> str:
        return self.value[0]

    @property
    def shelf_names(self) -> Tuple[str, ...]:
        """Display labels for this category's shelves."""
        return self.value[1]
