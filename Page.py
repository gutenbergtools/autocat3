#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
Page.py

Copyright 2009-2024 by Marcello Perathoner and Project Gutenberg

Distributable under the GNU General Public License Version 3 or newer.

Base class for all pages.

"""

from __future__ import unicode_literals

import logging

import cherrypy

from libgutenberg.DublinCore import DublinCore
from libgutenberg.MediaTypes import mediatypes as mt
from libgutenberg.GutenbergDatabase import DatabaseError

import BaseSearcher
import Formatters
from i18n_tool import ugettext as _

class Page(object):
    """ Base for all pages. """

    def __init__(self):
        self.supported_book_mediatypes = [ mt.epub, mt.mobi ]


    @staticmethod
    def format(os):
        """ Output page. """
        return Formatters.formatters[os.format].format(os.template, os)


    def client_book_mediatypes(self):
        """ Return the book mediatypes accepted by the client. """
        client_accepted_book_mediatypes = []

        accept_header = cherrypy.request.headers.get('Accept')

        if accept_header is None:
            client_accepted_book_mediatypes = self.supported_book_mediatypes
        else:
            #cherrypy.log("Accept: %s" % accept_header,
            #              context = 'REQUEST', severity = logging.DEBUG)

            client_accepted_book_mediatypes = []
            accepts = cherrypy.request.headers.elements('Accept')
            for accept in accepts:
                if accept.value in self.supported_book_mediatypes:
                    if accept.qvalue > 0:
                        client_accepted_book_mediatypes.append(accept.value)

        return client_accepted_book_mediatypes


class NullPage(Page):
    """ An empty page. """

    def index(self, **dummy_kwargs):
        """ Output an empty page. """
        return '<html/>'

class GoHomePage(Page):
    """ Go to start page. """
    def index(self, **kwargs):
        os = BaseSearcher.OpenSearch()
        raise cherrypy.HTTPRedirect(os.url('start'))

class SearchPage(Page):
    """ Abstract base class for all search page classes. """

    def setup(self, dummy_os, dummy_sql):
        """ Let derived classes setup the query. """
        raise NotImplementedError

    def fixup(self, os):
        """ Give derived classes a chance to further manipulate database results. """
        for e in os.entries:
            if '$' in e.title:
                e.title = DublinCore.strip_marc_subfields(e.title)

    def finalize(self, os):
        """ Give derived classes a chance to fix default finalization. """
        pass

    def nothing_found(self, os):
        """ Give derived class a chance to react if no records were found. """
        os.entries.insert(0, self.no_records_found(os))


    # this method is turned off; should remove it at some point
    def output_suggestions(self, os, max_suggestions_per_word=3, max_suggestions=9):
        """ Make suggestions. """

        # similarity == matching_trigrams / (len1 + len2 - matching_trigrams)

        sql_query = """
            SELECT
               word,
               nentry,
               similarity (word, %(word)s) AS sml
            FROM terms
            WHERE word %% %(word)s
            ORDER BY sml DESC, nentry DESC LIMIT %(suggestions)s;"""

        q = os.query.lower()
        words = q.split()
        words.sort(key=len, reverse=True) # only suggest on the longest words
        sugg = []
        done_words = []
        for word in words:
            if len(word) > 3 and word not in done_words:
                done_words.append(word)
                try:
                    rows = BaseSearcher.SQLSearcher().execute(
                        sql_query,
                        {'word': word, 'suggestions': max_suggestions_per_word + 1})
                    for i, row in enumerate(rows):
                        if i >= max_suggestions_per_word:
                            break
                        corr = row.word
                        if corr != word and (word, corr) not in sugg:
                            sugg.append((word, corr))
                except DatabaseError:
                    pass
            if len(sugg) > max_suggestions:
                break
        for word, corr in reversed(sugg):
            os.entries.insert(0, self.did_you_mean(os, corr, q.replace(word, corr)))



    def index(self, **kwargs):
        """ Output a search result page. """

        os = BaseSearcher.OpenSearch()
        os.log_request('search')

        if 'default_prefix' in kwargs:
            raise cherrypy.HTTPError(400, 'Bad Request. Unknown parameter: default_prefix')

        if os.start_index > BaseSearcher.MAX_RESULTS:
            raise cherrypy.HTTPError(400, 'Bad Request. Parameter start_index too high')

        sql = BaseSearcher.SQLStatement()
        sql.query = 'SELECT *'
        sql.from_ = ['v_appserver_books_4 as books']

        # let derived classes prepare the query
        try:
            self.setup(os, sql)
        except ValueError as what:
            cherrypy.log("SQL Error: " + str(what),
                          context='REQUEST', severity=logging.ERROR)
            raise cherrypy.HTTPError(400, 'Bad Request. ')

        os.fix_sortorder()

        # execute the query
        try:
            BaseSearcher.SQLSearcher().search(os, sql)
        except DatabaseError as what:
            cherrypy.log("SQL Error: " + str(what),
                          context='REQUEST', severity=logging.ERROR)
            raise cherrypy.HTTPError(400, 'Bad Request. Check your query.')

        # sync os.title and first entry header
        if os.entries:
            entry = os.entries[0]
            if os.title and not entry.header:
                entry.header = os.title
            elif entry.header and not os.title:
                os.title = entry.header

        os.template = os.page = 'results'

        # give derived class a chance to tweak result set
        self.fixup(os)

        # warn user about no records found
        if os.total_results == 0:
            self.nothing_found(os)

        # suggest alternate queries
        #if os.total_results < 5:
        #    self.output_suggestions(os)

        # add sort by links
        if os.start_index == 1 and os.total_results > 1:
            if 'downloads' in os.alternate_sort_orders:
                self.sort_by_downloads(os)
            if 'release_date' in os.alternate_sort_orders:
                self.sort_by_release_date(os)
            if 'title' in os.alternate_sort_orders:
                self.sort_by_title(os)
            if 'alpha' in os.alternate_sort_orders:
                self.sort_alphabetically(os)
            if 'author' in os.alternate_sort_orders:
                self.sort_by_author(os)
            if 'quantity' in os.alternate_sort_orders:
                self.sort_by_quantity(os)

        os.finalize()
        self.finalize(os)

        if os.total_results > 0:
            # call this after finalize()
            os.entries.insert(0, self.status_line(os))

        return self.format(os)


    @staticmethod
    def sort_by_downloads(os):
        """ Append the sort by downloads link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'popular'
        cat.title = _('Sort by Popularity')
        cat.url = os.url_carry(sort_order='downloads')
        cat.class_ += 'navlink grayed'
        cat.icon = 'popular'
        cat.order = 4.0
        os.entries.insert(0, cat)

    @staticmethod
    def sort_alphabetically(os):
        """ Append the sort alphabetically by title link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'alphabethical'
        cat.title = _('Sort Alphabetically by Title')
        cat.url = os.url_carry(sort_order='alpha')
        cat.class_ += 'navlink grayed'
        cat.icon = 'alpha'
        cat.order = 4.1
        os.entries.insert(0, cat)

    @staticmethod
    def sort_by_title(os):
        """ Append the sort alphabetically by title link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'alphabethical'
        cat.title = _('Sort Alphabetically by Title')
        cat.url = os.url_carry(sort_order='title')
        cat.class_ += 'navlink grayed'
        cat.icon = 'alpha'
        cat.order = 4.1
        os.entries.insert(0, cat)

    @staticmethod
    def sort_by_author(os):
        """ Append the sort alphabetically by author link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'alphabethical'
        cat.title = _('Sort Alphabetically by Author')
        cat.url = os.url_carry(sort_order='author')
        cat.class_ += 'navlink grayed'
        cat.icon = 'alpha'
        cat.order = 4.2
        os.entries.insert(0, cat)

    @staticmethod
    def sort_by_quantity(os):
        """ Append the sort by quantity link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'numerous'
        cat.title = _('Sort by Quantity')
        cat.url = os.url_carry(sort_order='quantity')
        cat.class_ += 'navlink grayed'
        cat.icon = 'quantity'
        cat.order = 4.3
        os.entries.insert(0, cat)

    @staticmethod
    def sort_by_release_date(os):
        """ Append the sort by release date link. """

        cat = BaseSearcher.Cat()
        cat.rel = 'new'
        cat.title = _('Sort by Release Date')
        cat.url = os.url_carry(sort_order='release_date')
        cat.class_ += 'navlink grayed'
        cat.icon = 'date'
        cat.order = 4.4
        os.entries.insert(0, cat)

    @staticmethod
    def status_line(os):
        """ Placeholder for status line. """

        cat = BaseSearcher.Cat()
        cat.rel = '__statusline__'
        cat.class_ += 'grayed'
        cat.icon = 'bibrec'
        cat.order = 10
        cat.header = os.title
        cat.title = _("Displaying results {from_}–{to} of {total}").format(
            from_ = os.start_index, to=os.end_index, total=os.total_results)
        return cat

    @staticmethod
    def no_records_found(os):
        """ Message. """

        cat = BaseSearcher.Cat()
        cat.rel = '__notfound__'
        cat.title = _('No records found.')
        cat.url = os.url('start')
        cat.class_ += 'navlink grayed'
        cat.icon = 'bibrec'
        cat.order = 11
        return cat

#    @staticmethod
#    def did_you_mean(os, corr, corrected_query):
#        """ Message. """
#
#        cat = BaseSearcher.Cat()
#        cat.rel = '__didyoumean__'
#        cat.title = _('Did you mean: {correction}').format(correction=corr)
#        cat.url = os.url('search', query=corrected_query)
#        cat.class_ += 'navlink'
#        cat.icon = 'suggestion'
#        cat.order = 12
#        return cat
