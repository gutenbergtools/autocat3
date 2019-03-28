#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
StartPage.py

Copyright 2009-2012 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The Search Start Page.

"""

from __future__ import unicode_literals

import BaseSearcher
import Page

class Start (Page.Page):
    """ The start page. """

    def index (self, **dummy_kwargs):
        """ Output the start page. """

        os = BaseSearcher.OpenSearch ()

        os.log_request ('start')

        os.search_terms = ''
        os.title = {
            'mobile': _('PG Mobile'),
            'opds':   _('Project Gutenberg'),
            'stanza': _('Project Gutenberg')
            }.get (os.format, _('Search Project Gutenberg'))

        cat = BaseSearcher.Cat ()
        cat.header = _(
            'Welcome to Project Gutenberg. Use the search box to find your book or pick a link.')
        cat.title = _('Popular')
        cat.subtitle = _('Our most popular books.')
        cat.url = os.url ('search', sort_order = 'downloads')
        cat.class_ += 'navlink'
        cat.icon = 'popular'
        cat.order = 2
        os.entries.append (cat)

        cat = BaseSearcher.Cat ()
        cat.title = _('Latest')
        cat.subtitle = _('Our latest releases.')
        cat.url = os.url ('search', sort_order = 'release_date')
        cat.class_ += 'navlink'
        cat.icon = 'date'
        cat.order = 3
        os.entries.append (cat)

        cat = BaseSearcher.Cat ()
        cat.title = _('Random')
        cat.subtitle = _('Random books.')
        cat.url = os.url ('search', sort_order = 'random')
        cat.class_ += 'navlink'
        cat.icon = 'random'
        cat.order = 4
        os.entries.append (cat)

        os.total_results = 0
        os.template = 'results'
        os.page = 'start'

        os.url_share = os.url ('/', host = os.file_host)
        os.twit  = os.tagline

        os.finalize ()

        return self.format (os)
