#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
AdvSearchPage.py

Copyright 2021 by Project Gutenberg

Distributable under the GNU General Public License Version 3 or newer.

Not really "advanced", it reproduces functionality of the old results.php search,
labelled as "Advanced Search", using SQLAlchemy ORM

Differences:
- instead of a link for a new search, a pre-filled advanced search form is shown contextually
- Following our Bibrecord pages, BC -> BCE in dates
- The language selector invokes some language-localization
- Authors are now all in a <ul>
- the first page of results is pageno=1, not 0
- cataloguer mode to list for missing subjects and loccs no longer supported 
    (no authentication in autocat3!)


"""
import cherrypy
import routes

from sqlalchemy import or_, and_

from libgutenberg.Models import (
    Alias, Attribute, Author, Book, BookAuthor, Category, File, Lang, Locc, Subject)

import BaseSearcher
from errors import ErrorPage
from Page import Page
from Formatters import formatters


config = cherrypy.config

BROWSE_KEYS = {'lang': 'languages', 'locc': 'loccs', 'category': 'categories'}
PAGESIZE = 100
MAX_RESULTS = 1000

_langs = {}
def langname(langcode):
    """ cache of Language names"""
    if not _langs:
        session = cherrypy.engine.pool.Session()
        for lang in session.query(Lang).all():
            _langs[lang.id] = lang.language
    return _langs.get(langcode, langcode)

_cats = {}
def catname(catpk):
    """ cache of category names"""
    if not _cats:
        session = cherrypy.engine.pool.Session()
        for cat in session.query(Category).all():
            _cats[cat.pk] = cat.category
    return _cats.get(catpk, 'Not a valid Category')


class AdvSearcher(BaseSearcher.OpenSearch):
    """ this object passes the context for the page renderer """
    def __init__(self):
        super().__init__()
        self.items_per_page = PAGESIZE

    def url(self, *args, **params):
        params = BaseSearcher.OpenSearch.params(**params)
        return super(AdvSearcher,self).url('results', *args, **params)

    def finalize(self):
        super().finalize()
        self.lastpage = int(self.total_results / PAGESIZE) + 1
        self.nextpage = self.pageno + 1 if self.pageno + 1 <= self.lastpage else 0
        self.prevpage = self.pageno - 1 if self.pageno > 1 <= self.lastpage else 0


class AdvSearchPage(Page):
    """ search term => list of items """
    def __init__(self):
        super().__init__()
        self.host = cherrypy.config['host']
        self.urlgen = routes.URLGenerator(cherrypy.routes_mapper, {'HTTP_HOST': self.host})
        self.formatter = formatters['html']

    def index (self, **kwargs):
        def entries(results, offset):
            """ results is a list of book ids, sorted by first Author,
            the query lazily returns book objects
            """
            query = session.query(Book).join(
                Book.authors.and_(BookAuthor.heading == 1)).join(BookAuthor.author).filter(
                Book.pk.in_(results)).order_by(Author.name).offset(offset).limit(PAGESIZE)

            for book in query:
                yield book


        os = AdvSearcher()
        params = cherrypy.request.params.copy()
        try:
            pageno = abs(int(params.pop("pageno", 1)))
        except KeyError:
            pageno = 1
        os.pageno = pageno
        for key in ["submit_search", "route_name", "controller", "action"]:
            params.pop(key, None)
        terms = [key for key in params if params[key]]

        # Return a search result page.

        # no terms provided
        if len(terms) == 0:
            os.total_results = 0
            os.finalize()
            return self.formatter.render('advresults', os)

        # single term, redirect if browsable
        if len(terms) == 1:
            browse_key = BROWSE_KEYS.get(terms[0], None)
            if browse_key:
                raise cherrypy.HTTPRedirect(
                    "/browse/%s/%s" % (browse_key, params[terms[0]].lower()))

        # multiple terms, create a query
        session = cherrypy.engine.pool.Session()
        query = session.query(Book.pk)
        selections = []
        resultpks = None
        searchterms = []
        for key in terms:
            if key in ['author', 'title', 'subject']:
                for word in params[key].split():
                    searchterms.append((key, word))
            else:
                searchterms.append((key, params[key]))

        for key, val in searchterms:
            if key == 'filetype':
                pks = query.join(File).filter(File.fk_filetypes == val).all()
                key = 'Filetype'

            elif key == 'lang':
                pks = query.join(Book.langs).filter(Lang.id == val).all()
                val = langname(val)
                key = 'Language'

            elif key == 'locc':
                pks = query.join(Book.loccs).filter(Locc.id == val).all()
                val = val.upper()
                key = 'LoC Class'

            elif key == 'category':
                try:
                    val = int(val)
                except ValueError:
                    continue
                pks = query.join(Book.categories).filter(Category.pk == val).all()
                val = catname(val)
                key = 'Category'

            elif key == 'author':
                word = "%{}%".format(val)
                subq = session.query(Author.id).join(Author.aliases).filter(
                    Alias.alias.ilike(word)).subquery()
                pks = query.join(Book.authors).join(BookAuthor.author).filter(or_(
                    Author.name.ilike(word),
                    Author.id.in_(subq),
                )).all()
                key = 'Author'

            elif key == 'title':
                word = "%{}%".format(val)
                pks = query.join(Book.attributes).filter(and_(
                    Attribute.fk_attriblist.in_([240, 245, 246, 505]),
                    Attribute.text.ilike(word),
                )).all()
                key = 'Title'

            elif key == 'subject':
                word = "%{}%".format(val)
                pks = query.join(Book.subjects).filter(                    
                    Subject.subject.ilike(word),
                ).all()
                key = 'Subject'

            pks = {row[0] for row in pks}
            resultpks = resultpks.intersection(pks) if resultpks is not None else pks
            num_rows = len(pks)
            selections.append((key, val, num_rows))

        os.total_results = len(resultpks)
        os.finalize()
        offset = PAGESIZE * (pageno - 1)
        os.start_index = offset + 1
        if os.total_results > MAX_RESULTS:
            os.entries = []
        else:
            os.entries = entries(resultpks, offset)
        os.search_terms = selections
        return self.formatter.render('advresults', os)
        