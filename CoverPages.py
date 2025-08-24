#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CoverPages.py

Copyright 2009-2021 by Project Gutenberg

Distributable under the GNU General Public License Version 3 or newer.

Serve cover images of most popular and latest ebooks.

"""

from __future__ import unicode_literals

import cherrypy
import six
from sqlalchemy import select
from sqlalchemy.sql import func

from libgutenberg import GutenbergGlobals as gg
from libgutenberg import DublinCore, DublinCoreMapping, Models



class CoverPages(object):
    """ Output a gallery of cover pages. """

    @staticmethod
    def serve(books, size, session):
        """ Output a gallery of coverpages. """

        def escape(_string):
            _string = gg.xmlspecialchars(_string) # handles <,>,&
            _string = _string.replace('"', '&quot;')
            _string = _string.replace("'", '&apos;')
            return _string

        def author_name(author):
            return escape(DublinCore.DublinCore.make_pretty_name(author.name))

        cherrypy.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        cherrypy.response.headers['Content-Language'] = 'en'
        s = ''
        for book_id in books:
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
                title = escape(dc.title)
            else:
                title = '!! missing title !!'

            short_title = escape(dc.make_pretty_title())

            
            author_name_list = map(author_name, dc.authors)

            authors = ', '.join(author_name_list)
            

            s += f"""
                <a href="{href}" title="{title}" data-authors="{authors}" target="_top">
                    <div class="cover_image">
                        <div class="cover_img">
                            <img src="{url}" alt="{title}, {authors}" title="{title}"
                             authors="{authors}" draggable="false">
                        </div>
                        <div class="cover_title">
                            <h5>{short_title}</h5>
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
            elif order == 'random':
                order_by = func.random()
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
        raise cherrypy.HTTPError(500, 'Internal Server Error.')
