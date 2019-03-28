#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
SuggestionsPage.py

Copyright 2012 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The search suggestions page.

"""

from __future__ import unicode_literals

import logging

import cherrypy

from libgutenberg.GutenbergDatabase import DatabaseError

import BaseSearcher
import Page

class Suggestions (Page.Page):
    """ Output the search suggestions page. """

    sql_searcher = BaseSearcher.SQLSearcher ()

    def index (self, **dummy_kwargs):
        """ Output the suggestions page. """

        cherrypy.request.params['format'] = 'json' # override user

        os = BaseSearcher.OpenSearch ()
        os.sort_order = 'nentry'
        os.start_index = 1
        os.items_per_page = 5

        if os.format != 'json':
            raise cherrypy.HTTPError (400, 'Bad Request. Unknown format.')

        if len (os.query) == 0:
            raise cherrypy.HTTPError (400, 'Bad Request. No query.')

        last_word = os.query.split ()[-1]
        if len (last_word) < 4:
            raise cherrypy.HTTPError (400, 'Bad Request. Query too short.')

        # ok. request looks sane. process it

        os.log_request ('suggestions')

        os.f_format_title = os.format_suggestion
        os.f_format_subtitle = os.format_none
        os.f_format_extra = os.format_none
        os.f_format_url = os.format_none
        os.f_format_thumb_url = os.format_none
        os.f_format_icon = os.format_none

        sql = BaseSearcher.SQLStatement ()

        # prepare inner query
        sql.query = 'SELECT tsvec'
        sql.from_ = ('books', )
        sql.fulltext ('books.tsvec', os.query)
        inner_sql_query = self.sql_searcher.mogrify (os, sql)

        sql.query = "SELECT substr (word, 2) AS title FROM ts_stat ( %(inner)s )"
        sql.from_ = ()
        sql.params['inner'] = inner_sql_query
        sql.where = ["word ~* %(re_word)s"]
        sql.params['re_word'] = '^0' + last_word

        try:
            os = self.sql_searcher.search (os, sql)
        except DatabaseError as what:
            cherrypy.log ("SQL Error: " + str (what),
                          context = 'REQUEST', severity = logging.ERROR)
            raise cherrypy.HTTPError (500, 'Internal Server Error.')

        os.template = os.page = 'results'
        os.finalize ()

        return self.format (os)
