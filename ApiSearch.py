import json

import cherrypy

from libgutenberg import DublinCore
from libgutenberg.DublinCoreMapping import DublinCoreObject
from libgutenberg.GutenbergDatabase import DatabaseError

import BaseSearcher 
from Page import SearchPage

# max no. of results returned by search
MAX_RESULTS = 100

class ApiSQLSearcher(BaseSearcher.SQLSearcher):

    def search(self, os, sql):
        """
        stripped down SQLSearcher; just gets book pks

        """
        sql.sort_order = os.sort_order
        sql.start_index = os.start_index
        sql.items_per_page = os.items_per_page
        query, params = sql.build()
        query += ' -- ' + os.ip

        rows = self.execute(query, params)

        # this is not necessarily the size of the result set.
        # if the result set is bigger than this page can show
        # total_results will be last item on page + 1
        os.total_results = min(os.start_index - 1 + len(rows), MAX_RESULTS)
        session = cherrypy.engine.pool.Session()
        for i in range(0, min(len(rows), os.items_per_page)):
            row = rows[i]
            pk = row.get('pk')
            book = DublinCoreObject(session=session)
            book.load_from_database(pk, load_files=False)
            os.entries.append(book)
        return os        

class ApiSearch (SearchPage):
    """ search term => list of books """

    def setup (self, os, sql):
        if len (os.query):
            sql.fulltext ('books.tsvec', os.query)


    def index(self, **kwargs):
        """ Output a search result page. """

        os = BaseSearcher.OpenSearch()

        if 'default_prefix' in kwargs:
            raise cherrypy.HTTPError(400, 'Bad Request. Unknown parameter: default_prefix')

        if os.start_index > BaseSearcher.MAX_RESULTS:
            raise cherrypy.HTTPError(400, 'Bad Request. Parameter start_index too high')

        sql = BaseSearcher.SQLStatement()
        sql.query = 'SELECT pk'
        sql.from_ = ['v_appserver_books_4 as books']

        # let derived classes prepare the query
        try:
            self.setup(os, sql)
        except ValueError as what:
            cherrypy.log("SQL Error: " + str(what),
                          context='REQUEST', severity=logging.ERROR)
            raise cherrypy.HTTPError(400, 'Bad Request. ')

        #os.fix_sortorder()

        # execute the query
        try:
            os = ApiSQLSearcher().search(os, sql)
        except DatabaseError as what:
            cherrypy.log("SQL Error: " + str(what),
                          context='REQUEST', severity=logging.ERROR)
            raise cherrypy.HTTPError(400, 'Bad Request. Check your query.')

        books = []
        for book in os.entries:
            titles = []
            for title_attr in book.book.attributes:
                if title_attr.fk_attriblist in {240, 245, 246}:
                    titles.append({'text': title_attr.text,
                                   'attr_code': title_attr.fk_attriblist,
                                   'source': title_attr.attribute_type.caption,
                                  })
                    
            books.append({'project_gutenberg_id': book.project_gutenberg_id,
                          'titles':titles})
        return json.dumps({'success': True, 'books': books})

