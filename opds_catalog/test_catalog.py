"""
test_catalog.py — tests for the OPDS catalog data layer.

Run: python3 -m unittest opds_catalog.test_catalog -v
Database-backed tests read connection settings from test.conf.
"""

import os
import unittest

import cherrypy
from sqlalchemy import create_engine

from .catalog import Catalog
from .constants import Crosswalk, Language, LoCCMainClass, OrderBy
from .publications import _set_publication_contributors, format_creators

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_CONF = os.path.join(ROOT, "test.conf")

_KNOWN_ETEXT = 1342
_OPDS_ACQ = "http://opds-spec.org/acquisition/open-access"


def _make_catalog() -> Catalog:
    cherrypy.config.update(TEST_CONF)
    c = cherrypy.config
    engine = create_engine(
        f"postgresql://{c['pguser']}@{c['pghost']}:{c['pgport']}/{c['pgdatabase']}"
    )
    return Catalog(engine)


class CatalogTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _make_catalog()

    def _run(self, query, expect_results=True):
        data = self.c.execute(query)
        if expect_results:
            self.assertGreater(data["total"], 0, data)
            self.assertTrue(data["results"])
        else:
            self.assertEqual(data["total"], 0, data)
        return data


class SearchTests(CatalogTestBase):
    def test_search(self):
        cases = (
            ("exact", self.c.query().search("Shakespeare")[1, 10]),
            ("typo falls back to fuzzy", self.c.query().search("Frankenstien")[1, 10]),
            (
                "author + subject",
                self.c.query().search("Shakespeare").search("Tragedy")[1, 10],
            ),
            (
                "title + bookshelf",
                self.c.query().search("Adventure").search("Children")[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class FilterTests(CatalogTestBase):
    def test_filters(self):
        cases = (
            ("etext()", self.c.query().etext(_KNOWN_ETEXT)[1, 10]),
            ("lang()", self.c.query().lang(Language.DE.code)[1, 10]),
            ("locc()", self.c.query().locc(LoCCMainClass.P)[1, 10]),
            ("author_id()", self.c.query().author_id(53)[1, 10]),
            ("subject_id()", self.c.query().subject_id(1)[1, 10]),
            ("bookshelf_id()", self.c.query().bookshelf_id(68)[1, 10]),
            ("also_downloaded()", self.c.query().also_downloaded(_KNOWN_ETEXT)[1, 10]),
            (
                "where()",
                self.c.query().where(
                    "COALESCE(array_length(creator_ids, 1), 0) > :n", n=2
                )[1, 10],
            ),
            (
                "search + lang",
                self.c.query().search("Adventure").lang("en")[1, 10],
            ),
            (
                "locc + search",
                self.c.query().locc(LoCCMainClass.P).search("Mystery")[1, 10],
            ),
        )
        for name, query in cases:
            with self.subTest(name=name):
                self._run(query)


class OrderingTests(CatalogTestBase):
    def test_ordering(self):
        for order in (
            OrderBy.DOWNLOADS,
            OrderBy.TITLE,
            OrderBy.AUTHOR,
            OrderBy.RELEVANCE,
            OrderBy.RELEASE_DATE,
            OrderBy.RANDOM,
        ):
            with self.subTest(order=order.value):
                self._run(self.c.query().search("Novel").order_by(order)[1, 10])


class PaginationTests(CatalogTestBase):
    def test_pagination(self):
        pages = []
        for page in (1, 2, 3):
            with self.subTest(page=page):
                data = self._run(self.c.query().search("Novel")[page, 5])
                pages.append({r["metadata"]["title"] for r in data["results"]})
        self.assertTrue(all(pages))
        self.assertNotEqual(pages[0], pages[1])
        self.assertNotEqual(pages[1], pages[2])

    def test_count(self):
        self.assertGreater(self.c.count(self.c.query().search("Shakespeare")), 0)


class CrosswalkTests(CatalogTestBase):
    def _etest(self, crosswalk):
        data = self.c.execute(self.c.query(crosswalk).etext(_KNOWN_ETEXT)[1, 1])
        self.assertEqual(data["total"], 1, data)
        return data["results"][0]

    def _author(self, metadata):
        author = metadata["author"]
        return author if isinstance(author, dict) else author[0]

    def test_crosswalk_opds(self):
        pub = self._etest(Crosswalk.OPDS)
        md, links = pub["metadata"], pub["links"]
        self.assertEqual(md["@type"], "http://schema.org/Book")
        self.assertEqual(md["identifier"], f"https://www.gutenberg.org/ebooks/{_KNOWN_ETEXT}")
        self.assertTrue(md["title"])
        self.assertTrue(md["language"])
        for key in ("accessibility", "description", "subject", "published"):
            self.assertIn(key, md)
        self.assertTrue(md["description"].startswith("Creators: "))
        self.assertNotIn("<p>", md["description"])
        self.assertIn("links", self._author(md))
        self.assertEqual(links[0]["rel"], "self")
        self.assertTrue(links[0]["href"].endswith(f"/opds/publications?id={_KNOWN_ETEXT}"))
        acq = [l for l in links if l.get("rel") == _OPDS_ACQ]
        self.assertEqual(len(acq), 1)
        self.assertEqual(acq[0]["type"], "application/epub+zip")
        self.assertTrue(any("/opds/also?" in l.get("href", "") for l in links))
        self.assertEqual(len(pub["images"]), 2)
        self.assertTrue(
            pub["images"][0]["href"].endswith(
                f"/cache/epub/{_KNOWN_ETEXT}/pg{_KNOWN_ETEXT}.cover.medium.jpg"
            )
        )

    def test_crosswalk_opds_small(self):
        pub = self._etest(Crosswalk.OPDS_SMALL)
        md, links = pub["metadata"], pub["links"]
        self.assertEqual(md["@type"], "http://schema.org/Book")
        self.assertTrue(md["title"])
        author = self._author(md)
        self.assertIn("name", author)
        self.assertIn("sortAs", author)
        for key in ("description", "accessibility", "published", "subject"):
            self.assertNotIn(key, md)
        self.assertNotIn("links", author)
        self.assertEqual(links[0]["rel"], "self")
        self.assertTrue(any(l.get("rel") == _OPDS_ACQ for l in links))
        self.assertFalse(any("/opds/also?" in l.get("href", "") for l in links))
        self.assertEqual(len(pub["images"]), 2)


class FormatCreatorsTests(unittest.TestCase):
    def test_single_author_with_dates(self):
        self.assertEqual(
            format_creators([{
                "name": "Twain, Mark", "role": "Author",
                "born_floor": 1835, "born_ceil": 1835,
                "died_floor": 1910, "died_ceil": 1910,
            }]),
            "Mark Twain (1835-1910)",
        )

    def test_role_and_partial_dates(self):
        self.assertEqual(
            format_creators([
                {"name": "Austen, Jane", "role": "Author",
                 "born_floor": 1775, "born_ceil": 1775,
                 "died_floor": 1817, "died_ceil": 1817},
                {"name": "Doe, Jane", "role": "Editor", "born_floor": 1900},
            ]),
            "Jane Austen (1775-1817) and Jane Doe (1900-) [Editor]",
        )

    def test_oxford_comma_uncertain_and_bce(self):
        self.assertEqual(
            format_creators([
                {"name": "Homer", "role": "Author", "born_floor": -750, "born_ceil": -750},
                {"name": "Smith, John (Jr.)", "role": "Translator", "died_ceil": 1850},
                {"name": "Plato", "role": "Author", "born_floor": -428, "born_ceil": -427},
            ]),
            "Homer (751 BCE-), John Smith (d. 1850?) [Translator], and Plato (428? BCE-)",
        )

    def test_skips_empty_names(self):
        self.assertEqual(format_creators([{"name": ""}, {"name": None}]), "")


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
        self.assertIn("identifier", metadata["translator"][0])
        self.assertIn("links", metadata["translator"][0])

    def test_narrator_maps_to_contributor(self):
        metadata = self._metadata_for(
            {"id": 1, "name": "Doe, Jane", "role": "Narrator"},
        )
        self.assertNotIn("author", metadata)
        self.assertEqual(metadata["contributor"]["name"], "Doe, Jane")

    def test_no_creators_omits_author(self):
        self.assertNotIn("author", self._metadata_for())


if __name__ == "__main__":
    unittest.main()
