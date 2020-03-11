#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CoverPages.py

Copyright 2009-2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Serve cover images of most popular and latest ebooks.

"""

from __future__ import unicode_literals

import cherrypy
import six

from libgutenberg import GutenbergGlobals as gg

import BaseSearcher

class CoverPages (object):
    """ Output a gallery of cover pages. """

    orders = { 'latest': 'release_date',
               'popular': 'downloads' }

    @staticmethod
    def serve (rows, size):
        """ Output a gallery of coverpages. """

        cherrypy.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        cherrypy.response.headers['Content-Language'] = 'en'

        s = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en" xml:base="http://www.gutenberg.org">
<head>
<title>Cover Flow</title>
<!--<style>
.cover-thumb {
        display: inline-block;
        background-position: center;
        background-repeat: no-repeat;
}
.cover-thumb-small {
	width:   76px;
	height: 110px;
}
.cover-thumb-medium {
	width:  210px;
	height: 310px;
}
</style>-->
</head>
<body><div>"""

        for row in rows:
            url = '/' + row.filename
            href = '/ebooks/%d' % row.pk
            title = gg.xmlspecialchars (row.title)
            title = title.replace ('"', '&quot;')

            s += """<a href="{href}"
                       title="{title}"
                       class="cover-thumb cover-thumb-{size}" target="_top"
                       style="background-image: url({url})"> </a>\n""".format (
                url = url, href = href, title = title, size = size)

 
        return (s + '</div></body></html>\n').encode ('utf-8')

    def index (self, count, size, order, **kwargs):
        """ Internal help function. """

        try:
            count = int (count)
            if count < 1:
                raise ValueError ('count < 0')
            if size not in ('small', 'medium'):
                raise ValueError ('bogus size')
            order = 'books.%s' % self.orders[order]

            rows = BaseSearcher.SQLSearcher.execute (
                """SELECT files.filename, books.pk, books.title FROM files, books
                WHERE files.fk_books = books.pk
                  AND files.diskstatus = 0
                  AND files.fk_filetypes = %%(size)s
                ORDER BY %s DESC
                OFFSET 1 LIMIT %%(count)s -- %s""" % (order, cherrypy.request.remote.ip),
                { 'count': count,
                  'size':  'cover.%s' % size,
                })

            if rows:
                return self.serve (rows, size)

        except (ValueError, KeyError) as what:
            raise cherrypy.HTTPError (400, 'Bad Request. %s' % six.text_type (what))
        except IOError:
            pass
        raise cherrypy.HTTPError (500, 'Internal Server Error.')
