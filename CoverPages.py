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
from sqlalchemy import select

from libgutenberg import GutenbergGlobals as gg
from libgutenberg import DublinCoreMapping, Models



class CoverPages(object):
    """ Output a gallery of cover pages. """

    @staticmethod
    def serve (books, size, session):
        """ Output a gallery of coverpages. """

        cherrypy.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        cherrypy.response.headers['Content-Language'] = 'en'
        
        s = ''
        for book_id in books:
            print(book_id, size)
            dc = DublinCoreMapping.DublinCoreObject(session=session, pooled=True)
            dc.load_from_database(book_id)
            cover = session.execute(select(Models.File.archive_path).where(
                Models.File.fk_books == book_id,
                Models.File.fk_filetypes == size)).scalars().first()
            if not cover:
                continue
            url = '/' + cover

            href = '/ebooks/%d' % book_id
            if dc.title: 
                title = gg.xmlspecialchars(dc.title) # handles <,>,&
                #Shortening long titles for latest covers
                title = title.replace('"', '&quot;')
                title = title.replace("'", '&apos;')
            else:
                title = '!! missing title !!'

            short_title = dc.make_pretty_title()
            
            authors = dc.authors[0].name
            

            s += f"""
                <a href="{href}" title="{title}" target="_top">
                    <div class="cover_image">
                        <div class="cover_img">
                            <img src="{url}" alt="{title}" title="{title}" draggable="false">
                        </div>
                        <div class="cover_title">
                            <h5>{short_title}</h5>
                        </div>
                        <div class="authors">
                            <h5>{authors}</h5>
                        </div>
                    </div>
                </a>
                """
        return s.encode('utf-8')

 
    def index(self, count, size, order, **kwargs):
        """ Internal help function. """

        session = cherrypy.engine.pool.Session()
        
        try:
            count = int(count)
            if count < 1:
                raise ValueError('count < 0')
            if size not in ('small', 'medium'):
                raise ValueError('bogus size')
            size = 'cover.%s' % size

            if order == 'popular':
                order_by = Models.Book.downloads.desc()
            else:
                order_by = Models.Book.release_date.desc()
            rows = session.execute(select(Models.Book.pk).where(
                Models.Book.pk == Models.File.fk_books,
                Models.File.fk_filetypes == size
            ).order_by(order_by).limit(count)).scalars().all()

            if rows:
                return self.serve(rows, size, session)

        except (ValueError, KeyError) as what:
            raise cherrypy.HTTPError (400, 'Bad Request. %s' % six.text_type(what))
        except IOError:
            pass
        finally:
            session.close()
        raise cherrypy.HTTPError (500, 'Internal Server Error.')
