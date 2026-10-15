#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
EbookCount.py

Copyright 2026 by Project Gutenberg

Distributable under the GNU General Public License Version 3 or newer.

Serve the exact ebook count as plain text for the homepage slogan.

"""

from __future__ import unicode_literals

import cherrypy

import BaseSearcher


class EbookCount(object):
    """ Serve the current ebook count as plain text. """

    def index(self, **dummy_kwargs):
        """ Return the cached ebook count, comma-grouped. """
        cherrypy.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return format(BaseSearcher.books_in_archive, ',d').encode('utf-8')
