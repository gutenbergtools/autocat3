#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CoverPages.py

Copyright 2009-2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Serve cover images of most popular and latest ebooks.

"""

from __future__ import unicode_literals
import re

import cherrypy
import six
import textwrap

from libgutenberg import GutenbergGlobals as gg

import BaseSearcher

class CoverPages(object):
    """ Output a gallery of cover pages. """

    orders = {'latest': 'release_date',
              'popular': 'downloads'}

    @staticmethod
    def serve (rows, size):
        """ Output a gallery of coverpages. """

        cherrypy.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        cherrypy.response.headers['Content-Language'] = 'en'
        s = ''
        for row in rows:
            url = '/' + row.filename
            href = '/ebooks/%d' % row.pk
            title = gg.xmlspecialchars (row.title) # handles <,>,&
              #Shortening long titles for latest covers
            title = title.replace('"', '&quot;')
            title = title.replace("'", '&apos;')
            short_title = title
            title_len = len(title)
            short_title = re.sub(r"\-+", " ", short_title)
            short_title = short_title.splitlines()[0]	    
            if(title_len > 80):
                short_title = textwrap.wrap(short_title, 80)[0]
            s += """
                <a href="{href}" title="{title}" target="_top">
                    <div class="cover_image">
                        <div class="cover_img">
                            <img src="{url}" alt="{title}" title="{title}" draggable="false">
                        </div>
                        <div class="cover_title">
                            <h5>{short_title}</h5>
                        </div>
                    </div>
                </a>
                """.format(url=url, href=href, title=title, short_title=short_title, size=size)

        return s.encode('utf-8')

 
    def index(self, count, size, order, **kwargs):
        """ Internal help function. """

        try:
            count = int(count)
            if count < 1:
                raise ValueError('count < 0')
            if size not in ('small', 'medium'):
                raise ValueError('bogus size')
            order = 'books.%s' % self.orders[order]

            rows = BaseSearcher.SQLSearcher.execute(
                """SELECT files.filename, books.pk, books.title FROM files, books
                WHERE files.fk_books = books.pk
                  AND files.diskstatus = 0
                  AND files.fk_filetypes = %%(size)s
                ORDER BY %s DESC
                OFFSET 1 LIMIT %%(count)s -- %s""" % (order, cherrypy.request.remote.ip),
                {'count': count, 'size': 'cover.%s' % size,}
            )

            if rows:
                return self.serve(rows, size)

        except (ValueError, KeyError) as what:
            raise cherrypy.HTTPError (400, 'Bad Request. %s' % six.text_type(what))
        except IOError:
            pass
        raise cherrypy.HTTPError (500, 'Internal Server Error.')
