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
]


class FileType(str, Enum):
    EPUB = "application/epub+zip"
    KINDLE = "application/x-mobipocket-ebook"
    PDF = "application/pdf"
    TXT = "text/plain"
    HTML = "text/html"


class SearchType(str, Enum):
    FTS = "fts"
    FUZZY = "fuzzy"


class SearchField(str, Enum):
    BOOK = "book"


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
            (640, "Crime, Thrillers & Mystery"),
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
            (673, "Research Methods/Statistics/Info Sys"),
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
        return self.value[1]
