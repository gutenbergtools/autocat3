import time

from .constants import (
    Crosswalk,
    Encoding,
    FileType,
    Language,
    LoCCMainClass,
    OrderBy,
    SearchType,
)
from .search import FullTextSearch

s = FullTextSearch()


def test(name: str, q):
    """Run a single test and print results."""
    start = time.perf_counter()
    try:
        data = s.execute(q)
        ms = (time.perf_counter() - start) * 1000
        count = data["total"]
        first = data["results"][0] if data["results"] else None
        if first:
            title = first.get("title", first.get("name", "N/A"))[:40]
            author = (first.get("author") or "Unknown")[:25]
        else:
            title, author = "N/A", "N/A"
        print(f"{name:<50} | {count:>6} | {ms:>7.1f}ms | {title} - {author}")
    except Exception as e:
        ms = (time.perf_counter() - start) * 1000
        print(f"{name:<50} | {'ERR':>6} | {ms:>7.1f}ms | {e}")


print("=" * 130)
print(f"{'Test':<50} | {'Count':>6} | {'Time':>8} | First Result")
print("=" * 130)

# === Search: FTS ===
print("-" * 130)
print("FTS Search (stemming, GIN tsvector)")
print("-" * 130)
test("FTS BOOK", s.query().search("Shakespeare")[1, 10])

# === Search: FUZZY ===
print("-" * 130)
print("FUZZY Search (typo-tolerant, GiST trigram)")
print("-" * 130)
test(
    "FUZZY BOOK",
    s.query().search("Shakspeare", search_type=SearchType.FUZZY)[1, 10],
)

# === Filters: PK ===
print("-" * 130)
print("Filters: Primary Key")
print("-" * 130)
test("etext()", s.query().etext(1342)[1, 10])
test("etexts()", s.query().etexts([1342, 84, 11])[1, 10])

# === Filters: B-tree ===
print("-" * 130)
print("Filters: B-tree")
print("-" * 130)
test("downloads_gte()", s.query().downloads_gte(10000)[1, 10])
test("downloads_lte()", s.query().downloads_lte(100)[1, 10])
test("public_domain()", s.query().public_domain()[1, 10])
test("copyrighted()", s.query().copyrighted()[1, 10])
test("text_only()", s.query().text_only()[1, 10])
test("audiobook()", s.query().audiobook()[1, 10])
test("author_born_after()", s.query().author_born_after(1900)[1, 10])
test("author_born_before()", s.query().author_born_before(1700)[1, 10])

# === Filters: Date ===
print("-" * 130)
print("Filters: Date")
print("-" * 130)
test("released_after()", s.query().released_after("2020-01-01")[1, 10])
test("released_before()", s.query().released_before("2000-01-01")[1, 10])

# === Filters: GIN Array / JSONB ===
print("-" * 130)
print("Filters: GIN Array / JSONB")
print("-" * 130)
test("lang()", s.query().lang(Language.DE)[1, 10])
test("locc()", s.query().locc(LoCCMainClass.P)[1, 10])
test("contributor_role()", s.query().contributor_role("Illustrator")[1, 10])
test("file_type() EPUB", s.query().file_type(FileType.EPUB)[1, 10])
test("file_type() PDF", s.query().file_type(FileType.PDF)[1, 10])
test("file_type() TXT", s.query().file_type(FileType.TXT)[1, 10])
test(
    "file_type() KINDLE",
    s.query().search("Computers").file_type(FileType.KINDLE)[1, 10],
)
test("author_id()", s.query().author_id(53)[1, 10])
test("subject_id()", s.query().subject_id(1)[1, 10])
test("bookshelf_id()", s.query().bookshelf_id(68)[1, 10])
test("encoding() UTF8", s.query().encoding(Encoding.UTF8)[1, 10])
test("encoding() ASCII", s.query().encoding(Encoding.ASCII)[1, 10])
test("author_died_after()", s.query().author_died_after(1950)[1, 10])
test("author_died_before()", s.query().author_died_before(1800)[1, 10])

# === Chained Searches (AND logic) ===
print("-" * 130)
print("Chained Searches (AND logic)")
print("-" * 130)
test(
    "FTS AUTHOR + FTS SUBJECT",
    s.query()
    .search("Shakespeare")
    .search("Tragedy")[1, 10],
)
test(
    "FTS TITLE + FTS BOOKSHELF",
    s.query()
    .search("Adventure")
    .search("Children")[1, 10],
)
test(
    "FUZZY AUTHOR + FTS TITLE",
    s.query()
    .search("Shakspeare", search_type=SearchType.FUZZY)
    .search("Hamlet")[1, 10],
)

# === Custom SQL ===
print("-" * 130)
print("Custom SQL")
print("-" * 130)
test(
    "where() - multi-author",
    s.query().where("COALESCE(array_length(creator_ids, 1), 0) > :n", n=2)[1, 10],
)
test(
    "where() - has credits",
    s.query().where("COALESCE(array_length(credits, 1), 0) > 0")[1, 10],
)

# === Ordering ===
print("-" * 130)
print("Ordering")
print("-" * 130)
test(
    "order_by(DOWNLOADS)", s.query().search("Novel").order_by(OrderBy.DOWNLOADS)[1, 10]
)
test("order_by(TITLE)", s.query().search("Novel").order_by(OrderBy.TITLE)[1, 10])
test("order_by(AUTHOR)", s.query().search("Novel").order_by(OrderBy.AUTHOR)[1, 10])
test(
    "order_by(RELEVANCE)", s.query().search("Novel").order_by(OrderBy.RELEVANCE)[1, 10]
)
test(
    "order_by(RELEASE_DATE)",
    s.query().search("Novel").order_by(OrderBy.RELEASE_DATE)[1, 10],
)
test("order_by(RANDOM)", s.query().search("Novel").order_by(OrderBy.RANDOM)[1, 10])

# === Combined Filters ===
print("-" * 130)
print("Combined Filters")
print("-" * 130)
test(
    "FTS + lang + public_domain",
    s.query().search("Adventure").lang(Language.EN).public_domain()[1, 10],
)
test("FTS + file_type", s.query().search("Novel").file_type(FileType.EPUB)[1, 10])
test(
    "FUZZY TITLE + downloads_gte",
    s.query()
    .search("Shakspeare", search_type=SearchType.FUZZY)
    .downloads_gte(1000)[1, 10],
)
test("author_id + file_type", s.query().author_id(53).file_type(FileType.TXT)[1, 10])
test(
    "FTS BOOKSHELF + lang",
    s.query().search("Mystery").lang(Language.EN)[1, 10],
)
test("locc + public_domain", s.query().locc(LoCCMainClass.P).public_domain()[1, 10])

# === Crosswalk Formats ===
print("-" * 130)
print("Crosswalk Formats")
print("-" * 130)

start = time.perf_counter()
data = s.execute(s.query(Crosswalk.PG).search("Shakespeare")[1, 5])
ms = (time.perf_counter() - start) * 1000
first = data["results"][0] if data["results"] else {}
print(
    f"{'Crosswalk.PG':<50} | {data['total']:>6} | {ms:>7.1f}ms | keys: {list(first.keys())}"
)
if first:
    print(
        f"  -> ebook_no: {first.get('ebook_no')}, files: {len(first.get('files', []))}, contributors: {len(first.get('contributors', []))}"
    )
    if first.get('contributors'):
        c = first['contributors'][0]
        print(
            f"  -> first contributor: {c.get('name')}, born: {c.get('born_floor')}-{c.get('born_ceil')}, died: {c.get('died_floor')}-{c.get('died_ceil')}"
        )
    # Test ContributorFormat: fmt() = main author, fmt(all=True) = all authors
    fmt = first.get('format')
    if fmt:
        print(f"  -> fmt():                                     {fmt()}")
        print(f"  -> fmt(pretty=True):                          {fmt(pretty=True)}")
        print(f"  -> fmt(pretty=True, dates=False):             {fmt(pretty=True, dates=False)}")
        print(f"  -> fmt(all=True):                             {fmt(all=True)}")
        print(f"  -> fmt(all=True, pretty=True):                {fmt(all=True, pretty=True)}")
        print(f"  -> fmt(all=True, strunk_join=True):           {fmt(all=True, strunk_join=True)}")
        print(f"  -> fmt(all=True, strunk_join=True, pretty=True): {fmt(all=True, strunk_join=True, pretty=True)}")

start = time.perf_counter()
data = s.execute(s.query(Crosswalk.OPDS).search("Shakespeare")[1, 5])
ms = (time.perf_counter() - start) * 1000
first = data["results"][0] if data["results"] else {}
print(
    f"{'Crosswalk.OPDS':<50} | {data['total']:>6} | {ms:>7.1f}ms | keys: {list(first.get('metadata', {}).keys())}"
)

# === Pagination ===
print("-" * 130)
print("Pagination")
print("-" * 130)
test("page 1", s.query().search("Novel")[1, 5])
test("page 2", s.query().search("Novel")[2, 5])
test("page 3", s.query().search("Novel")[3, 5])

# === Count-only ===
print("-" * 130)
print("Count-only")
print("-" * 130)
start = time.perf_counter()
count = s.count(s.query().search("Shakespeare"))
ms = (time.perf_counter() - start) * 1000
print(f"{'count()':<50} | {count:>6} | {ms:>7.1f}ms | (count only)")

# === Custom Transformer ===
print("-" * 130)
print("Custom Transformer")
print("-" * 130)


def my_transformer(row):
    author = " | ".join(row.creator_names) if row.creator_names else "Unknown"
    return {
        "id": row.book_id,
        "name": f"{row.title} by {author}",
        "popularity": row.downloads,
    }


s.set_custom_transformer(my_transformer)
start = time.perf_counter()
data = s.execute(s.query(Crosswalk.CUSTOM).search("Shakespeare")[1, 5])
ms = (time.perf_counter() - start) * 1000
first = data["results"][0] if data["results"] else {}
print(f"{'Crosswalk.CUSTOM':<50} | {data['total']:>6} | {ms:>7.1f}ms | {first}")

print("=" * 130)
print("All tests complete!")
