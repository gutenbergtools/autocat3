#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
Sitemap.py

Copyright 2009-2013 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Output a Google sitemap.

"""

from __future__ import unicode_literals
from __future__ import division

import datetime

import cherrypy

from libgutenberg.GutenbergGlobals import Struct

import TemplatedPage
import BaseSearcher

SITEMAP_SIZE = 1000   # max no. of urls to put into one sitemap


class Sitemap (TemplatedPage.TemplatedPage):
    """ Output Google sitemap. """

    def index (self, **kwargs):
        """ Output sitemap. """

        urls = []
        start = int (kwargs['page']) * SITEMAP_SIZE

        rows = BaseSearcher.SQLSearcher.execute (
            'select pk from books where pk >= %(start)s and pk <  %(end)s order by pk',
            { 'start': str (start), 'end': str (start + SITEMAP_SIZE) })

        os = BaseSearcher.OpenSearch ()
        host = cherrypy.config['host']

        for row in rows:
            url = Struct ()
            url.loc = os.url ('bibrec', id = row[0], host = host, format = None)
            urls.append (url)

        data = Struct ()
        data.urls = urls

        return self.output ('sitemap', data = data)


class SitemapIndex (TemplatedPage.TemplatedPage):
    """ Output Google sitemap index. """

    def index (self, **dummy_kwargs):
        """ Output sitemap index. """

        sitemaps = []
        now = datetime.datetime.utcnow ().replace (microsecond = 0).isoformat () + 'Z'

        # 99999 is safeguard against bogus ebook numbers
        lastbook = BaseSearcher.sql_get ('select max (pk) as lastbook from books where pk < 99999')

        os = BaseSearcher.OpenSearch ()
        host = cherrypy.config['host']

        for n in range (0, lastbook // SITEMAP_SIZE + 1):
            sitemap = Struct ()
            sitemap.loc = os.url ('sitemap_index', page = n, host = host, format = None)
            sitemap.lastmod = now
            sitemaps.append (sitemap)

        data = Struct ()
        data.sitemaps = sitemaps

        return self.output ('sitemap-index', data = data)
