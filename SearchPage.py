#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
SearchPage.py

Copyright 2009-2012 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The various flavors of search page.

"""

from __future__ import unicode_literals
import re
import cherrypy

from libgutenberg.MediaTypes import mediatypes as mt
from libgutenberg.DublinCore import DublinCore

import BaseSearcher
from Page import SearchPage
from i18n_tool import ugettext as _
from i18n_tool import ungettext as __
from catalog import catname, langname, locname

hr_terms = {
    'l.': lambda x: f' Language: {langname(x)} ',
    'lcc.': lambda x: f' Library of Congress Class: {locname(x)} ',
#    'cat.': lambda x: f' Category: {catname(x)} ',
}

MATCH_TERM = re.compile(r'(\b\w+\.)(\w+)')


class BookSearchPage (SearchPage):
    """ search term => list of books """

    def setup (self, os, sql):
        os.sort_orders = ('downloads', 'release_date', 'title', 'random')
        os.icon = 'book'
        os.class_ += 'booklink'
        os.f_format_icon = os.format_icon_titles
        
        os.title = os.query
        for match in MATCH_TERM.finditer(os.query):
            if match.group(1) in hr_terms:
                prefixed = match.group(0)
                repl = f'{hr_terms.get(match.group(1))(match.group(2))}'
                os.title = os.title.replace(prefixed, repl)

        if os.sort_order == 'random':
            sql.where.append ("pk in (select pk from books order by random() limit 20)")
        if len (os.query):
            sql.fulltext ('books.tsvec', os.query)
            os.title = _("Books: {title}").format (title = os.title)
        else:
            os.title = _('All Books')


    def fixup (self, os):
        """ strip marc subfields, add social media hints and facet links """
        os.icon = 'book'
        for e in os.entries:
            if '$' in e.title:
                e.title = DublinCore.strip_marc_subfields (e.title)

        if (os.sort_order == 'release_date' and os.total_results > 0 and os.start_index == 1):
            cat = BaseSearcher.Cat ()
            cat.title = _('Follow new books on Mastodon')
            cat.subtitle = _("Like and follow to see our new books in your feed.")
            cat.url = 'https://mastodon.social/@gutenberg_new'
            cat.class_ += 'navlink grayed'
            cat.icon = 'masto'
            cat.order = 5
            os.entries.insert (0, cat)

            cat = BaseSearcher.Cat ()
            cat.title = _('Follow new books on Bluesky')
            cat.subtitle = _("Boost and follow to see our new books in your feed.")
            cat.url = 'https://bsky.app/profile/new.gutenberg.org'
            cat.class_ += 'navlink grayed'
            cat.icon = 'bsky'
            cat.order = 5
            os.entries.insert (0, cat)

            cat = BaseSearcher.Cat ()
            cat.title = _('Follow new books on Facebook')
            cat.subtitle = _("Like and follow to see our new books in your feed.")
            cat.url = 'https://www.facebook.com/gutenberg.new'
            cat.class_ += 'navlink grayed'
            cat.icon = 'facebook'
            cat.order = 5
            os.entries.insert (0, cat)

        if (len (os.query) and os.start_index == 1):
            sql2 = BaseSearcher.SQLStatement ()
            sql2.query = "select count (*) from bookshelves"
            sql2.fulltext ('bookshelves.tsvec', os.query)
            rows = BaseSearcher.SQLSearcher.execute (*sql2.build ())
            if rows[0][0] > 0:
                cat = BaseSearcher.Cat ()
                cat.rel = 'related'
                cat.title = _('Bookshelves')
                cat.subtitle = __('One bookshelf matches your query.',
                                  '{count} bookshelves match your search.',
                                  rows[0][0]).format (count = rows[0][0])
                cat.url = os.url ('bookshelf_search', query = os.query)
                cat.class_ += 'navlink grayed'
                cat.icon = 'bookshelf'
                cat.order = 3
                os.entries.insert (0, cat)

            sql2 = BaseSearcher.SQLStatement ()
            sql2.query = "select count (*) from subjects"
            sql2.fulltext ('subjects.tsvec', os.query)
            rows = BaseSearcher.SQLSearcher.execute (*sql2.build ())
            if rows[0][0] > 0:
                cat = BaseSearcher.Cat ()
                cat.rel = 'related'
                cat.title = _('Subjects')
                cat.subtitle = __('One subject heading matches your search.',
                                 '{count} subject headings match your search.',
                                 rows[0][0]).format (count = rows[0][0])
                cat.url = os.url ('subject_search', query = os.query)
                cat.class_ += 'navlink grayed'
                cat.icon = 'subject'
                cat.order = 3
                os.entries.insert (0, cat)

            sql2 = BaseSearcher.SQLStatement ()
            sql2.query = "select count (*) from authors"
            sql2.fulltext ('authors.tsvec', os.query)
            rows = BaseSearcher.SQLSearcher.execute (*sql2.build ())
            if rows[0][0] > 0:
                cat = BaseSearcher.Cat ()
                cat.rel = 'related'
                cat.title = _('Authors')
                cat.subtitle = __('One author name matches your search.',
                                  '{count} author names match your search.',
                                  rows[0][0]).format (count = rows[0][0])
                cat.url = os.url ('author_search', query = os.query)
                cat.class_ += 'navlink grayed'
                cat.icon = 'author'
                cat.order = 3
                os.entries.insert (0, cat)


class AuthorSearchPage (SearchPage):
    """ name => list of authors """

    def setup (self, os, sql):
        os.f_format_subtitle = os.format_subtitle
        os.f_format_url = BaseSearcher.SearchUrlFormatter ('author')
        os.f_format_thumb_url = os.format_none
        os.sort_orders = ('downloads', 'quantity', 'alpha', 'release_date')
        os.icon = 'author'
        os.class_ += 'navlink'
        os.title = _('All Authors')

        sql.query = """
                    SELECT
                       authors.author as title,
                       coalesce (authors.born_floor || '', '') || '-' ||
                          coalesce (authors.died_floor || '', '') as subtitle,
                       authors.pk as pk,
                       max (books.release_date) as release_date,
                       sum (books.downloads) as downloads,
                       count (books.pk) as quantity"""

        sql.from_ = ('authors', 'mn_books_authors as mn', 'books')
        sql.groupby += ('authors.author', 'subtitle', 'authors.pk')
        sql.where.append ('authors.pk = mn.fk_authors')
        sql.where.append ('books.pk = mn.fk_books')

        if len (os.query):
            sql.fulltext ('authors.tsvec', os.query)
            os.title = _("Authors: {author}").format (author = os.query)
        else:
            sql.where.append ("authors.author not in ('Various', 'Anonymous', 'Unknown')")


class SubjectSearchPage (SearchPage):
    """ term => list of subects """

    def setup (self, os, sql):
        os.f_format_url = BaseSearcher.SearchUrlFormatter ('subject')
        os.f_format_thumb_url = os.format_none
        os.sort_orders = ('downloads', 'quantity', 'alpha', 'release_date')
        os.icon = 'subject'
        os.class_ += 'navlink'
        os.title = _('All Subjects')

        sql.query = """
                    SELECT
                       subjects.subject as title,
                       subjects.pk as pk,
                       max (books.release_date) as release_date,
                       sum (books.downloads) as downloads,
                       count (books.pk) as quantity"""

        sql.from_ = ('subjects', 'mn_books_subjects as mn', 'books')
        sql.groupby += ('subjects.subject', 'subjects.pk')
        sql.where.append ('subjects.pk = mn.fk_subjects')
        sql.where.append ('books.pk = mn.fk_books')

        if len (os.query):
            sql.fulltext ('subjects.tsvec', os.query)
            os.title = _("Subjects: {subject}").format (subject = os.query)


class BookshelfSearchPage (SearchPage):
    """ term => list of bookshelves """

    def setup (self, os, sql):
        os.f_format_url = BaseSearcher.SearchUrlFormatter ('bookshelf')
        os.f_format_thumb_url = os.format_none
        os.sort_orders = ('downloads', 'quantity', 'alpha', 'release_date', 'authors')
        os.icon = 'bookshelf'
        os.title_icon = 'bookshelf'
        os.class_ += 'navlink'
        os.title = _('All Bookshelves')

        sql.query = """
                    SELECT
                       bookshelves.bookshelf as title,
                       bookshelves.pk as pk,
                       max (books.release_date) as release_date,
                       sum (books.downloads) as downloads,
                       count (books.pk) as quantity"""

        sql.from_ = ('bookshelves', 'mn_books_bookshelves as mn', 'books')
        sql.groupby += ('bookshelves.bookshelf', 'bookshelves.pk')
        sql.where.append ('bookshelves.pk = mn.fk_bookshelves')
        sql.where.append ('books.pk = mn.fk_books')

        if len (os.query):
            sql.fulltext ('bookshelves.tsvec', os.query)
            os.title = _("Bookshelves: {bookshelf}").format (bookshelf = os.query)


class AuthorPage (SearchPage):
    """ author id => books by author """

    def setup (self, os, sql):
        os.sort_orders = ('downloads', 'title', 'release_date')
        os.title_icon = 'author'
        os.icon = 'book'
        os.class_ += 'booklink'
        os.f_format_icon = os.format_icon_titles
        os.author = BaseSearcher.sql_get (
            "select author from authors where pk = %(pk)s", pk = os.id)
        os.title = _('Books by {author}').format (author = os.author)

        sql.from_.append ('mn_books_authors as mn')
        sql.where.append ('books.pk = mn.fk_books')
        sql.where.append ("mn.fk_authors = %(fk_authors)s")
        sql.params['fk_authors'] = os.id

    def fixup (self, os):
        for e in os.entries:
            if '$' in e.title:
                e.title = DublinCore.strip_marc_subfields (e.title)

        if (os.start_index == 1 and len (os.entries) > 0):

            # browse-by-author page for maintainers
            if 'is-catalog-maintainer' in cherrypy.request.cookie:
                cat = BaseSearcher.Cat ()
                cat.type = mt.html
                cat.rel = 'related'
                cat.title = _('Browse by Author')
                cat.url = "/browse/authors/%s#a%d" % (os.author[:1].lower (), os.id)
                cat.class_ += 'navlink grayed'
                cat.icon = 'internal'
                cat.order = 9
                os.entries.insert (0, cat)

            # wikipedia links etc.
            rows = BaseSearcher.SQLSearcher.execute (
                """SELECT url, description AS title FROM author_urls
                   WHERE fk_authors = %(fk_authors)s""",
                { 'fk_authors': os.id } )
            for row in rows:
                cat = BaseSearcher.Cat ()
                cat.type = mt.html
                cat.rel = 'related'
                cat.title = _('See also: {title}').format (title = row.title)
                cat.url = row.url
                cat.class_ += 'navlink grayed'
                cat.icon = 'external'
                cat.order = 8
                os.entries.insert (0, cat)

            # author aliases
            if os.format  == 'html':
                rows = BaseSearcher.SQLSearcher.execute (
                    """SELECT alias AS title FROM aliases
                       WHERE fk_authors = %(fk_authors)s AND alias_heading = 1""",
                    { 'fk_authors': os.id }
                    )

                for row in rows:
                    cat = BaseSearcher.Cat ()
                    cat.title = _('Alias {alias}').format (alias = row.title)
                    cat.class_ += 'grayed'
                    cat.icon = 'alias'
                    cat.order = 7
                    os.entries.insert (0, cat)


class SubjectPage (SearchPage):
    """ subject id => books about subject """

    def setup (self, os, sql):
        os.sort_orders = ('downloads', 'title', 'release_date')
        os.title_icon = 'subject'
        os.icon = 'book'
        os.class_ += 'booklink'
        os.f_format_icon = os.format_icon_titles
        os.subject = BaseSearcher.sql_get (
            "select subject from subjects where pk = %(pk)s", pk = os.id)
        os.title = _('Books about {subject}').format (subject = os.subject)

        sql.from_.append ('mn_books_subjects as mn')
        sql.where.append ('books.pk = mn.fk_books')
        sql.where.append ("mn.fk_subjects = %(fk_subjects)s")
        sql.params['fk_subjects'] = os.id


class BookshelfPage (SearchPage):
    """ bookshelf id => books on bookshelf """

    def setup (self, os, sql):
        os.sort_orders = ('downloads', 'title', 'author', 'release_date')
        os.title_icon = 'bookshelf'
        os.icon = 'book'
        os.class_ += 'booklink'
        os.f_format_icon = os.format_icon_titles
        os.bookshelf = BaseSearcher.sql_get (
            "select bookshelf from bookshelves where pk = %(pk)s", pk = os.id)
        os.title = _('Books in {bookshelf}').format (bookshelf = os.bookshelf)

        sql.from_.append ('mn_books_bookshelves as mn')
        sql.where.append ('books.pk = mn.fk_books')
        sql.where.append ("mn.fk_bookshelves = %(fk_bookshelves)s")
        sql.params['fk_bookshelves'] = os.id


class AlsoDownloadedPage (SearchPage):
    """ ebook id => books people also downloaded """

    def setup (self, os, sql):
        os.sort_orders = ('downloads', )
        os.icon = 'book'
        os.class_ += 'booklink'
        os.f_format_icon = os.format_icon_titles
        os.title = _('Readers also downloaded')

        sql.query = """
                    SELECT
                       books.pk,
                       books.title,
                       books.filing,
                       books.author,
                       books.release_date,
                       books.fk_categories,
                       books.fk_langs,
                       books.coverpages,
                       d.dl as downloads
                    FROM
                      v_appserver_books_4 as books
                        JOIN (
                          SELECT
                            s1.fk_books as pk, count (s1.id) as dl
                          FROM
                            scores.also_downloads as s1,
                            scores.also_downloads as s2
                          WHERE s2.fk_books = %(fk_books)s
                            AND s1.fk_books != %(fk_books)s
                            AND s1.id = s2.id
                          GROUP BY s1.fk_books) as d
                        ON d.pk = books.pk"""
        sql.from_ = ()
        sql.params['fk_books'] = os.id


    def finalize (self, os):
        # one page is enough
        os.show_next_page_link = False
