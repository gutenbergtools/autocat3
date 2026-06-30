"""
test_search.py — integration tests for the mv_books_dc search module.

Run: python3 -m unittest mv_search.test_search -v
"""

import os
import unittest

import cherrypy
from sqlalchemy import create_engine

from .constants import (
    Crosswalk,
    FileType,
    Language,
    LoCCMainClass,
    OrderBy,
    SearchField,
    SearchType,
)
from .Search import FullTextSearch
from .crosswalks import _set_publication_contributors

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_CONF = os.path.join(ROOT, "test.conf")


def _make_search() -> FullTextSearch:
    cherrypy.config.update(TEST_CONF)
    c = cherrypy.config
    engine = create_engine(
        f"postgresql://{c['pguser']}@{c['pghost']}:{c['pgport']}/{c['pgdatabase']}"
    )
    return FullTextSearch(engine)


class SearchTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _make_search()

    def _run(self, query, expect_results=True):
        data = self.s.execute(query)
        if expect_results:
            self.assertGreater(data["total"], 0, data)
            self.assertTrue(data["results"])
        else:
            self.assertEqual(data["total"], 0, data)
        return data


class SearchTypeTests(SearchTestBase):
    def test_search_types(self):
        cases = (
            ("FTS BOOK", self.s.query().search("Shakespeare")[1, 10], True),
            (
                "FUZZY BOOK",
                self.s.query().search("Frankenstien", search_type=SearchType.FUZZY)[
                    1, 10
                ],
                True,
            ),
            (
                "HYBRID BOOK (exact)",
                self.s.query().search("Shakespeare", search_type=SearchType.HYBRID)[
                    1, 10
                ],
                True,
            ),
            (
                "HYBRID BOOK (typo)",
                self.s.query().search("Frankenstien", search_type=SearchType.HYBRID)[
                    1, 10
                ],
                True,
            ),
            ("FTS typo (no hit)", self.s.query().search("Frankenstien")[1, 10], False),
        )
        for name, query, expect in cases:
            with self.subTest(name=name):
                self._run(query, expect_results=expect)


class FieldScopedSearchTests(SearchTestBase):
    def test_field_scoped(self):
        cases = (
            ("FTS TITLE", self.s.query().search("Hamlet", field=SearchField.TITLE)[1, 10]),
            (
                "FTS AUTHOR",
                self.s.query().search("Shakespeare", field=SearchField.AUTHOR)[1, 10],
            ),
            (
                "FUZZY TITLE",
                self.s.query().search(
                    "Hamlett", field=SearchField.TITLE, search_type=SearchType.FUZZY
                )[1, 10],
            ),
            (
                "FUZZY AUTHOR",
                self.s.query().search(
                    "Shakspeare",
                    field=SearchField.AUTHOR,
                    search_type=SearchType.FUZZY,
                )[1, 10],
            ),
            (
                "HYBRID TITLE (exact)",
                self.s.query().search(
                    "Hamlet", field=SearchField.TITLE, search_type=SearchType.HYBRID
                )[1, 10],
            ),
            (
                "HYBRID AUTHOR (typo)",
                self.s.query().search(
                    "Shakspeare",
                    field=SearchField.AUTHOR,
                    search_type=SearchType.HYBRID,
                )[1, 10],
            ),
            (
                "TITLE + AUTHOR (AND)",
                self.s.query()
                .search("Romeo", field=SearchField.TITLE)
                .search("Shakespeare", field=SearchField.AUTHOR)[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class PrimaryKeyFilterTests(SearchTestBase):
    def test_primary_key_filters(self):
        cases = (
            ("etext()", self.s.query().etext(1342)[1, 10]),
            ("etexts()", self.s.query().etexts([1342, 84, 11])[1, 10]),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class BTreeFilterTests(SearchTestBase):
    def test_btree_filters(self):
        cases = (
            ("downloads_gte()", self.s.query().downloads_gte(10000)[1, 10]),
            ("downloads_lte()", self.s.query().downloads_lte(100)[1, 10]),
            ("public_domain()", self.s.query().public_domain()[1, 10]),
            ("copyrighted()", self.s.query().copyrighted()[1, 10]),
            ("text_only()", self.s.query().text_only()[1, 10]),
            ("audiobook()", self.s.query().audiobook()[1, 10]),
            ("author_born_after()", self.s.query().author_born_after(1900)[1, 10]),
            ("author_born_before()", self.s.query().author_born_before(1700)[1, 10]),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class DateFilterTests(SearchTestBase):
    def test_date_filters(self):
        cases = (
            ("released_after()", self.s.query().released_after("2020-01-01")[1, 10]),
            ("released_before()", self.s.query().released_before("2000-01-01")[1, 10]),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class GinFilterTests(SearchTestBase):
    def test_gin_filters(self):
        cases = (
            ("lang()", self.s.query().lang(Language.DE)[1, 10]),
            ("locc()", self.s.query().locc(LoCCMainClass.P)[1, 10]),
            ("contributor_role()", self.s.query().contributor_role("Illustrator")[1, 10]),
            ("file_type() EPUB", self.s.query().file_type(FileType.EPUB)[1, 10]),
            ("file_type() PDF", self.s.query().file_type(FileType.PDF)[1, 10]),
            ("file_type() TXT", self.s.query().file_type(FileType.TXT)[1, 10]),
            (
                "file_type() KINDLE",
                self.s.query().search("Computers").file_type(FileType.KINDLE)[1, 10],
            ),
            ("author_id()", self.s.query().author_id(53)[1, 10]),
            ("subject_id()", self.s.query().subject_id(1)[1, 10]),
            ("bookshelf_id()", self.s.query().bookshelf_id(68)[1, 10]),
            ("author_died_after()", self.s.query().author_died_after(1950)[1, 10]),
            ("author_died_before()", self.s.query().author_died_before(1800)[1, 10]),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class ChainedSearchTests(SearchTestBase):
    def test_chained_searches(self):
        cases = (
            (
                "FTS AUTHOR + FTS SUBJECT",
                self.s.query().search("Shakespeare").search("Tragedy")[1, 10],
            ),
            (
                "FTS TITLE + FTS BOOKSHELF",
                self.s.query().search("Adventure").search("Children")[1, 10],
            ),
            (
                "FUZZY AUTHOR + FTS TITLE",
                self.s.query()
                .search("Shakspeare", search_type=SearchType.FUZZY)
                .search("Hamlet")[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class CustomSqlTests(SearchTestBase):
    def test_custom_sql(self):
        cases = (
            (
                "where() - multi-author",
                self.s.query().where(
                    "COALESCE(array_length(creator_ids, 1), 0) > :n", n=2
                )[1, 10],
            ),
            (
                "where() - has credits",
                self.s.query().where("COALESCE(array_length(credits, 1), 0) > 0")[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class OrderingTests(SearchTestBase):
    def test_ordering(self):
        cases = (
            (
                "order_by(DOWNLOADS)",
                self.s.query().search("Novel").order_by(OrderBy.DOWNLOADS)[1, 10],
            ),
            ("order_by(TITLE)", self.s.query().search("Novel").order_by(OrderBy.TITLE)[1, 10]),
            (
                "order_by(AUTHOR)",
                self.s.query().search("Novel").order_by(OrderBy.AUTHOR)[1, 10],
            ),
            (
                "order_by(RELEVANCE)",
                self.s.query().search("Novel").order_by(OrderBy.RELEVANCE)[1, 10],
            ),
            (
                "order_by(RELEASE_DATE)",
                self.s.query().search("Novel").order_by(OrderBy.RELEASE_DATE)[1, 10],
            ),
            (
                "order_by(RANDOM)",
                self.s.query().search("Novel").order_by(OrderBy.RANDOM)[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class CombinedFilterTests(SearchTestBase):
    def test_combined_filters(self):
        cases = (
            (
                "FTS + lang + public_domain",
                self.s.query().search("Adventure").lang(Language.EN).public_domain()[1, 10],
            ),
            (
                "FTS + file_type",
                self.s.query().search("Novel").file_type(FileType.EPUB)[1, 10],
            ),
            (
                "FUZZY TITLE + downloads_gte",
                self.s.query()
                .search("Shakspeare", search_type=SearchType.FUZZY)
                .downloads_gte(1000)[1, 10],
            ),
            (
                "author_id + file_type",
                self.s.query().author_id(53).file_type(FileType.TXT)[1, 10],
            ),
            (
                "FTS BOOKSHELF + lang",
                self.s.query().search("Mystery").lang(Language.EN)[1, 10],
            ),
            (
                "locc + public_domain",
                self.s.query().locc(LoCCMainClass.P).public_domain()[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class CrosswalkTests(SearchTestBase):
    def test_crosswalk_pg(self):
        data = self.s.execute(self.s.query(Crosswalk.PG).search("Shakespeare")[1, 5])
        self.assertGreater(data["total"], 0)
        first = data["results"][0]
        self.assertIn("ebook_no", first)
        self.assertIn("files", first)
        self.assertIn("contributors", first)
        self.assertTrue(first["contributors"])
        contributor = first["contributors"][0]
        self.assertIn("name", contributor)
        self.assertIn("born_floor", contributor)
        self.assertIn("died_floor", contributor)
        fmt = first.get("format")
        self.assertTrue(callable(fmt))
        self.assertTrue(fmt())
        self.assertTrue(fmt(pretty=True))
        self.assertTrue(fmt(pretty=True, dates=False))
        self.assertTrue(fmt(all=True))
        self.assertTrue(fmt(all=True, pretty=True))
        self.assertTrue(fmt(all=True, strunk_join=True))
        self.assertTrue(fmt(all=True, strunk_join=True, pretty=True))

    def test_crosswalk_opds(self):
        data = self.s.execute(self.s.query(Crosswalk.OPDS).search("Shakespeare")[1, 5])
        self.assertGreater(data["total"], 0)
        first = data["results"][0]
        self.assertIn("metadata", first)
        self.assertIn("links", first)
        self.assertIn("title", first["metadata"])
        self.assertIn("description", first["metadata"])

    def test_crosswalk_opds_small(self):
        data = self.s.execute(
            self.s.query(Crosswalk.OPDS_SMALL).search("Shakespeare")[1, 5]
        )
        self.assertGreater(data["total"], 0)
        first = data["results"][0]
        self.assertIn("metadata", first)
        self.assertIn("links", first)
        self.assertIn("title", first["metadata"])
        self.assertNotIn("description", first["metadata"])
        self.assertEqual(first["links"][0]["rel"], "self")
        self.assertTrue(
            any(
                l.get("rel") == "http://opds-spec.org/acquisition/open-access"
                for l in first["links"]
            )
        )
        self.assertIn("images", first)
        self.assertEqual(len(first["images"]), 2)
        self.assertEqual(first["images"][0]["rel"], "http://opds-spec.org/image")
        self.assertEqual(first["images"][1]["rel"], "http://opds-spec.org/image/thumbnail")


class OpdsContributorTests(unittest.TestCase):
    def _metadata_for(self, *creators, with_search_link=False):
        publication_metadata = {}
        _set_publication_contributors(
            publication_metadata, list(creators), with_search_link=with_search_link
        )
        return publication_metadata

    def test_author_and_introduction_contributor(self):
        metadata = self._metadata_for(
            {"id": 68, "name": "Austen, Jane", "role": "Author"},
            {"id": 77, "name": "Someone Else", "role": "Author of introduction, etc."},
        )
        self.assertEqual(metadata["author"]["name"], "Austen, Jane")
        self.assertEqual(metadata["contributor"]["name"], "Someone Else")

    def test_translator_only_no_author_field(self):
        metadata = self._metadata_for(
            {"id": 55321, "name": "Renouf, P. Le Page", "role": "Translator"},
            {"id": 55322, "name": "Naville, Edouard", "role": "Translator"},
            with_search_link=True,
        )
        self.assertNotIn("author", metadata)
        self.assertEqual(len(metadata["translator"]), 2)
        self.assertIn("links", metadata["translator"][0])

    def test_narrator_maps_to_contributor(self):
        metadata = self._metadata_for(
            {"id": 1, "name": "Doe, Jane", "role": "Narrator"},
        )
        self.assertNotIn("author", metadata)
        self.assertEqual(metadata["contributor"]["name"], "Doe, Jane")

    def test_collaborator_maps_to_contributor(self):
        metadata = self._metadata_for(
            {"id": 1, "name": "Smith, John", "role": "Collaborator"},
        )
        self.assertNotIn("author", metadata)
        self.assertEqual(metadata["contributor"]["name"], "Smith, John")

    def test_no_creators_omits_author(self):
        self.assertNotIn("author", self._metadata_for())


class PaginationTests(SearchTestBase):
    def test_pagination(self):
        cases = (
            ("page 1", self.s.query().search("Novel")[1, 5]),
            ("page 2", self.s.query().search("Novel")[2, 5]),
            ("page 3", self.s.query().search("Novel")[3, 5]),
        )
        pages = []
        for name, query in cases:
            with self.subTest(name=name):
                data = self._run(query)
                pages.append({row.get("title") for row in data["results"]})
        self.assertTrue(pages[0])
        self.assertTrue(pages[1])
        self.assertTrue(pages[2])
        self.assertNotEqual(pages[0], pages[1])
        self.assertNotEqual(pages[1], pages[2])


class CountTests(SearchTestBase):
    def test_count(self):
        count = self.s.count(self.s.query().search("Shakespeare"))
        self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
