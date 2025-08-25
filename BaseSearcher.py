#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
BaseSearcher.py

Copyright 2009-2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Project Gutenberg Catalog Search
Base class

"""

from __future__ import unicode_literals
from __future__ import division

import datetime
import logging

from six.moves import urllib
import cherrypy
import routes
import babel
import regex  # module re does not support \p{L}
import six

from libgutenberg.MediaTypes import mediatypes as mt
from libgutenberg.GutenbergDatabase import xl, DatabaseError
from libgutenberg import DublinCore
from libgutenberg import GutenbergDatabaseDublinCore
from libgutenberg import GutenbergGlobals as gg

from i18n_tool import ugettext as _
from i18n_tool import ungettext as __

import DublinCoreI18n
from SupportedLocales import FB_LANGS, TWITTER_LANGS, GOOGLE_LANGS, PAYPAL_LANGS, FLATTR_LANGS

VALID_PROTOCOLS = ('http', 'https')

MEDIATYPE_TO_FORMAT = {
    'text/html': 'html',
    mt.mobile: 'html',
    mt.opds: 'opds',
    mt.json: 'json',
}

USER_FORMATS = 'html mobile print opds stanza json'.split()

# max no. of results returned by search
MAX_RESULTS = 5000

# sort orders available to the user
SORT_ORDERS = 'downloads author release_date title alpha quantity nentry random'.split()

# fk_categories of sound files
AUDIOBOOK_CATEGORIES = set([1, 2, 3, 6])

language_map = gg.language_map()

# updated by cron thread
books_in_archive = 0


class ClassAttr(object):
    """ Holds an XML class attribute. """

    __slots__ = 'value'

    def __init__(self, v=None):
        self.value = set()
        self.__iadd__(v)

    def __len__(self):
        return len(self.value)

    def __unicode__(self):
        return ' '.join(self.value) if self.value else ''

    def __str__(self):
        return ' '.join(self.value) if self.value else ''

    def __iadd__(self, v):
        """ Implements operator += """
        if not v:
            return self

        if isinstance(v, six.string_types):
            for i in six.text_type(v).split():
                self.value.add(i)
            return self

        if isinstance(v, ClassAttr):
            self.value |= v.value
            return self

    def __contains__(self, b):
        return b in self.value


class DC(GutenbergDatabaseDublinCore.GutenbergDatabaseDublinCore,
          DublinCoreI18n.DublinCoreI18nMixin):
    """ A localized DublinCore. """

    def __init__(self, pool):
        GutenbergDatabaseDublinCore.GutenbergDatabaseDublinCore.__init__(self, pool)
        DublinCoreI18n.DublinCoreI18nMixin.__init__(self)


class Cat(object):
    """ Hold data of one list item in output. """

    def __init__(self):
        self.type = None # use default
        self.header = ''
        self.class_ = ClassAttr()
        self.downloads = 1
        self.rel = None
        self.order = 0
        self.charset = None
        self.title = None
        self.subtitle = None
        self.extra = None
        self.icon = None
        self.icon2 = None
        self.url = None
        self.thumb_url = None


class SearchUrlFormatter(object):
    """ Callable to format a search url. """

    def __init__(self, action):
        self.action = action

    def __call__(self, row):
        os = cherrypy.request.os
        return os.url(
            self.action,
            format = os.format,
            id = row.pk)


class SQLStatement(object):
    """ Class implementing an SQL statement. """

    prefix_to_prefix = {
        'a.': 'ax',
        't.': 'tx',
        's.': 'sx',
        'bs.': 'bsx',
        'l.': 'l0',
        '#': 'no.',
        'n.': 'no.',
        'type.': 'y0',
        'lcn.': 'lcnx',
        'lcc.': 'lcc0',
        'cat.': 'cat0',
    }
    """Dict of user-visible prefixes to translate.

    User-visible prefixes must be easy to type. The dot is on the
    lowercase keyboard of most phones, so you need no shifting to type
    these.

    Internal prefixes exploit the quirks of the tsvec stemmer. Words
    containing numbers do not get stemmed, so any '*0' prefix searches
    for the unstemmed word. All other words get stemmed, so any '*x'
    prefix searches for the stem of the word. 'x' was selected because
    it is a rare character that will cause few false positives.

    """

    regex_cache = {}
    """ Cache of compiled regexes. """

    def __init__(self):
        self.query = ''
        self.params = {}
        self.from_ = []
        self.where = []
        self.groupby = []
        self.sort_order = None
        self.start_index = 1
        self.items_per_page = -1


    @classmethod
    def sub(cls, regex_, replace, query):
        """ Like re.sub but also compile and cache the regex. """
        if not isinstance(query, str):
            query = query[0] if isinstance(query, list) and len(query) > 0 else ''

        cregex = cls.regex_cache.setdefault(
            regex_, regex.compile(regex_, regex.UNICODE | regex.VERSION1))
        return cregex.sub(replace, query)


    @classmethod
    def preprocess_query(cls, query):
        """ Preprocess query.

        The preprocessed query might get echoed to the user.
        """

        sub = cls.sub

        # strip most not (letter or digit)
        # \p{Z} : Separator
        # \p{P} : Punctuation
        # \p{S} : Symbol
        # \p{M} : Mark
        # \p{C} : Other

        query = sub(r'[\p{Z}\p{P}\p{S}\p{M}\p{C}--.!|()#]', ' ', query)

        # strip operators adjacent to non-whitespace
        # if you want grouping you have to add space on both sides of the parens
        query = sub(r'\b[!)]', ' ', query)
        query = sub(r'[(]\b', ' ', query)

        # insert spaces around operators
        query = sub(r'\s*[|!()]\s*', r' \g<0> ', query)

        # remove empty groups
        query = sub(r'\s*\([.!|()#\s]+\)\s*', ' ', query)
        return ' '.join(query.split())


    @classmethod
    def translate_query(cls, query):
        """ Translate query from user syntax to postgres tsvec syntax. """

        sub = cls.sub

        def prefix_sub(match_object):
            """ Translate from user-visible prefix to internal prefix. """
            s = match_object.group(0)
            return cls.prefix_to_prefix.get(s, s)

        def balance(query):
            """ Balance parens. """
            def scan(query, up, down):
                scan = ''
                depth = 0
                for char in query:
                    if char == up:
                        depth += 1
                        scan += char
                    elif char == down:
                        depth += -1
                        if depth < 0:
                            depth = 0
                        else:
                            scan += char
                    else:
                        scan += char
                return scan, depth
            balanced, depth = scan(query, '(', ')')
            if depth:
                balanced, depth = scan(balanced[::-1], ')', '(')
                balanced = balanced[::-1]
            return balanced

        # Replace the user-visible prefixes with the internally used prefixes.
        query = sub(r'(\b\w+\.|#)(?=\w)', prefix_sub, query)

        # add wildcards to all words
        query = sub(r'\b(\p{L}+)(\s|$)', r'\1:*\2', query)
        query = query.replace('. ', ' ')

        # if parens aren't balanced, remove them
        query = balance(query)

        # if ! or | are at the wrong ends, remove them
        query = sub(r'(^[ \|]+|[ \|\!]+$)', '', query)

        # replace ' ' with ' & '
        query = ' '.join(query.split())
        query = sub(r'(?<![|!(\s])\s+(?![|)])', ' & ', query)

        return query


    def build(self):
        """ Returns the SQL query string and parameter array. """

        query = self.query

        if self.from_:
            query += " FROM " + ", ".join(self.from_)

        if self.where:
            query += " WHERE " + " AND ".join(self.where)

        if self.groupby:
            query += " GROUP BY " + ", ".join(self.groupby)

        params = self.params

        if self.sort_order in SORT_ORDERS:
            if self.sort_order == 'random':
                query += " ORDER BY random ()"
            elif self.sort_order == 'title':
                query += " ORDER BY filing"
            elif self.sort_order == 'alpha':
                query += " ORDER BY title"
            elif self.sort_order == 'author':
                query += " ORDER BY author"
            elif self.sort_order == 'release_date':
                query += " ORDER BY release_date DESC, pk DESC"
            else:
                query += " ORDER BY %s DESC" % (self.sort_order)

        if self.start_index > 1:
            # opensearch is 1-based, SQL is 0-based
            params['offset'] = self.start_index - 1
            query += " OFFSET %(offset)s"

        if self.items_per_page > -1:
            # need one more to know when to display 'next' link
            params['limit']  = self.items_per_page + 1
            query += " LIMIT %(limit)s"

        return query, params


    def split(self, field, query):
        """ Split multiple-term query for sql consumption. """

        terms = []
        n = len(self.params)
        for i, q in enumerate(query.split()):
            q = q.strip('.,:;')
            terms.append("%s ~* %%(p%d)s" % (field, n + i))
            # self.params['p%d' % (n + i)] = r'\m' + q
            self.params['p%d' % (n + i)] = '(^| )' + q

        return terms

    def split_and_append(self, field, query):
        """ Split multiple-term query for sql consumption and append terms to query. """

        for term in self.split(field, query):
            self.where.append(term)


    def fulltext(self, field, query, stemmer='english'):
        """ Perform fulltext search on query words. """

        query = query.strip()
        if len(query) == 0:
            return
        query = self.translate_query(query)

        self.where.append("%s @@ to_tsquery('%s', %%(p%d)s)" %
                           (field, stemmer, len(self.params)))

        self.params['p%d' % len(self.params)] = query


class OpenSearch(object):
    """ Hold search results and lots of other stuff.

    We use this to pass everything we know around and into the
    templating engine.

    """

    lang_to_default_locale = {
        'en': 'en_US',
        'de': 'de_DE',
        'fr': 'fr_FR',
        'es': 'es_ES',
        'it': 'it_IT',
        'pt': 'pt_BR',
        'ru': 'ru_RU',
    }

    def __init__(self):
        self.format = None
        self.page = None
        self.template = None
        self.query = None
        self.id = None
        self.sort_order = None
        self.search_terms = None
        self.start_index = 1
        self.items_per_page = 1
        self.total_results = -1
        self.page_mode = 'screen'
        self.user_dialog = ('', '')
        self.opensearch_support = 0 # 0 = none, 1 = full, 2 = fake(Stanza, Aldiko, ...)
        self.books_in_archive = babel.numbers.format_number(
            books_in_archive, locale = str(cherrypy.response.i18n.locale))
        self.breadcrumbs  = [
            (_('Project Gutenberg'), _('Go to the Main page.'), '/'),
            (__('1 free eBook', '{count} free eBooks', books_in_archive).format(
                count = self.books_in_archive), _('Start a new search.'), '/ebooks/'),
        ]

        # default output formatting functions
        self.f_format_title = self.format_title
        self.f_format_subtitle = self.format_author
        self.f_format_extra = self.format_none # depends on sort order, set in fix_sortorder ()
        self.f_format_url = self.format_bibrec_url
        self.f_format_thumb_url = self.format_thumb_url
        self.f_format_icon = self.format_icon # icon class

        self.user_agent = cherrypy.request.headers.get('User-Agent', '')

        cherrypy.request.os = self
        s = cherrypy.session
        k = cherrypy.request.params

        host = cherrypy.request.headers.get('X-Forwarded-Host', cherrypy.config['host'])
        self.host = host.split(',')[-1].strip() # keep only the last hub
        # turns out X-Forwarded-Protocol (X-Forwarded-Proto is the defacto standaard)
        # is not a thing and has to be set in HAProxy
        self.protocol = cherrypy.request.headers.get('X-Forwarded-Protocol', 'https')

        # sanity check
        if self.host not in (cherrypy.config['all_hosts']):
            self.host = cherrypy.config['host']
        if self.protocol not in VALID_PROTOCOLS:
            self.protocol = 'https'

        self.urlgen = routes.URLGenerator(cherrypy.routes_mapper, {'HTTP_HOST': self.host})

        self.set_format(k.get('format'))

        # query: this param is set when an actual query is requested

        self.query = ''
        if 'query' in k:
            self.query = SQLStatement.preprocess_query(k['query'])

        # search_terms: this is used to carry the last query
        # to display in the search input box

        self.search_terms = self.query or s.get('search_terms', '')

        self.sort_order = k.get('sort_order') or s.get('sort_order') or SORT_ORDERS[0]
        if self.sort_order not in SORT_ORDERS:
            raise cherrypy.HTTPError(400, 'Bad Request. Unknown sort order.')
        # can't combine random with other sorts!
        if self.sort_order != 'random':
            s['sort_order'] = self.sort_order

        try:
            self.id = int(k.get('id') or '0')
        except (ValueError, TypeError) as what:
            self.id = 0
        try:
            self.start_index = int(k.get('start_index') or '1')
        except (ValueError, TypeError) as what:
            self.start_index = 1
        try:
            self.items_per_page = min(100, int(k.get('items_per_page') or '25'))
        except (ValueError, TypeError) as what:
            self.items_per_page = 25


        self.file_host = cherrypy.config['file_host']
        self.now = datetime.datetime.utcnow().replace(microsecond = 0).isoformat() + 'Z'
        self.do_animations = 'Kindle/' not in self.user_agent # no animations on e-ink
        self.ip = cherrypy.request.remote.ip
        self.type_opds = 'application/atom+xml;profile=opds-catalog'

        self.base_url = None
        self.canonical_url = None
        self.read_url = None
        self.entries = []

        # NOTE: For page titles etc.
        self.pg = self.title = _('Project Gutenberg')
        # NOTE: The tagline at the top of every page.
        self.tagline = _('Project Gutenberg offers {count} free eBooks to download.').format(
            count = self.books_in_archive)
        # NOTE: The site's description in the html meta tags.
        self.description = _('Project Gutenberg offers {count} free eBooks for '
                             'Kindle, iPad, Nook, Android, and iPhone.').format(
                                 count = self.books_in_archive)
        # NOTE: The placeholder inside an empty search box.
        self.placeholder = _('Search Project Gutenberg.')

        # these need to be here because they have to be localized
        # NOTE: Msg to user indicating the order of the search results.
        self.sorted_msgs = {
            'downloads': _("sorted by popularity"),
            'release_date': _("sorted by release date"),
            'quantity': _("sorted by quantity of books"),
            'title': _("sorted alphabetically"),
            'alpha': _("sorted alphabetically by title"),
            'author': _("sorted alphabetically by author"),
            'nentry': _("sorted by relevance"),
            'random': _("in random order"),
            }

        self.snippet_image_url = self.url('/pics/logo-144x144.png', host=self.file_host)
        self.og_type = 'website'
        self.class_ = ClassAttr()
        self.title_icon = 'search'
        self.icon = None
        self.sort_orders = []
        self.alternate_sort_orders = []

        lang = self.lang = s.get('_lang_', 'en_US')
        if len(lang) == 2:
            lang = self.lang_to_default_locale.get(lang, 'en_US')
        lang2 = self.lang[:2]

        self.paypal_lang = lang if lang in PAYPAL_LANGS else 'en_US'
        self.flattr_lang = lang if lang in FLATTR_LANGS else 'en_US'

        lang = lang.replace('_', '-')

        self.google_lang  = lang if lang in GOOGLE_LANGS  else (
            lang2 if lang2 in GOOGLE_LANGS else 'en-US')
        lang = lang.lower()
        self.twitter_lang = lang if lang in TWITTER_LANGS else (
            lang2 if lang2 in TWITTER_LANGS else 'en')

        self.viewport = "width=device-width" # , initial-scale=1.0"
        self.touch_icon = '/gutenberg/apple-icon.png'
        self.touch_icon_precomposed = None # not yet used

        if 'user_dialog' in s:
            self.user_dialog = s['user_dialog']
            del s['user_dialog']

        msg = k.get('msg')
        if msg is not None:
            if msg == 'welcome_stranger':
                self.user_dialog = (
                    _("Welcome to Project Gutenberg. "
                      "You'll find here {count} eBooks completely free of charge.")
                    .format(count = self.books_in_archive),
                    _('Welcome'))


    def finalize(self):
        """ Calculate fields that depend on start_index, items_per_page and total_results.

        start_index, etc. must be set before calling this.

        """

        self.desktop_host = cherrypy.config['host']

        last_page = max((self.total_results - 1) // self.items_per_page, 0) # 0-based

        self.end_index = min(self.start_index + self.items_per_page - 1, self.total_results)

        self.prev_page_index = max(self.start_index - self.items_per_page, 1)
        self.next_page_index = min(self.start_index + self.items_per_page, self.total_results)
        self.last_page_index = last_page * self.items_per_page + 1

        self.show_prev_page_link = self.start_index > 1
        self.show_next_page_link = (self.end_index < self.total_results)

        self.desktop_search = self.url('search', format = None)

        self.base_url = self.url(host = self.file_host, protocol='https')

        # for google, fb etc.
        self.canonical_url = self.url_carry(host = self.file_host, format = None)

        self.desktop_url = self.url_carry(host = self.desktop_host, format = None)

        self.osd_url = self.qualify('/catalog/osd-books.xml')

        s = cherrypy.session
        # write this late so pages can change it
        s['search_terms'] = self.search_terms


    def url(self, *args, **params):
        """ Generate url carrying the 'format' parameter from self.

        See: http://tools.cherrypy.org/wiki/RoutesUrlGeneration """

        # We need to explicitly carry the parameters in the query
        # string (eg. those not matched by routes) because routes has
        # no memory for those.
        #
        # Also route memory is not used when generating named routes
        # eg. url('search').

        params.setdefault('format', str(self.format))

        route_name = args[0] if args else str(cherrypy.request.params['route_name'])
        rn = cherrypy.routes_mapper._routenames # pylint: disable=protected-access
        if route_name in rn:
            route_obj = rn[route_name]
            if 'id' in route_obj.minkeys:
                params.setdefault('id', str(self.id))

        # Eliminate null and superflous params.
        for k, v in list(params.items()):
            try:
                if v is None or (k == 'start_index' and
                             int(v) < 2) or (k == 'format' and v == 'html'):
                    del params[k]
            except (ValueError, TypeError) as what:
                del params[k]
        return self.urlgen(route_name, **params)


    @staticmethod
    def params(**kwargs):
        """ Get dict of current params with override option. """
        d = cherrypy.request.params.copy()
        # del d['action']
        # del d['controller']
        # del d['route_name']
        try:
            del d['fb_locale']
        except KeyError:
            pass
        d.update(kwargs)
        return d


    def url_carry(self, *args, **params):
        """ Generate url carrying most params from self. """

        return self.url(*args, **self.params(**params))


    @staticmethod
    def add_amp(url):
        """ Add ? or & to url. """
        if '?' in url:
            return url + '&'
        return url + '?'


    def qualify(self, url):
        """ Append host part. """
        return urllib.parse.urljoin(self.base_url, url)


    def set_format(self, format_):
        """ Sanity check and set the parameter we got from the user.
        Calc format and mediatype to send to the client. """

        if format_ and format_ not in USER_FORMATS:
            raise cherrypy.HTTPError(400, 'Bad Request. Unknown format.')

        # fold print into html
        if format_ == 'print':
            format_ = 'html'
            self.page_mode = 'print'

        # user explicitly requested format
        if format_:
            self.format = 'html' if format_ == 'mobile' else format_
            self.mediatype = mt[format_]
            self.opensearch_support = 1 if format_ == 'opds' else 2
            return

        # no specific format requested

        ua = self.user_agent

        format_ = 'html'
        mediatype = 'text/html'
        opensearch_support = 0

        # user accessed the mobile site

        # known OPDS consumers
        # 'stanza' is the older opds-ish format supported by stanza et al.

        if ua:
            if ua.startswith('Stanza/'):
                # Stanza/2.1.1 iPhone OS/3.1.3/iPod touch catalog/2.1.1
                # Stanza/3.0 iPhone OS/3.1.3/iPod touch catalog/3.0
                format_ = 'stanza'
                mediatype = mt.opds
                opensearch_support = 2
            elif ua.startswith('FBReader/'):
                # FBReader/0.6.6(java)
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif 'Aldiko/' in ua:
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 2
            elif ua.startswith('Ibis-Reader/'):
                # Ibis-Reader/0.1
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif ua.startswith('ouiivo'):
                # ouiivo
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif (ua.startswith('QuickR') or
                  ua.startswith('Young Reader') or
                  ua.startswith('MegaRead') or
                  ua.startswith('eBook Search')):
                # MegaReadLite 1.0 (iPhone Simulator; iPhone OS 4.2; en_US)
                # QuickReader 2.1.0 (iPhone; iPhone OS 3.1.3; en_US)
                # QuickRdrLite 3.0.1 (iPhone Simulator; iPhone OS 4.2; en_US)
                # eBook Search1.0(iPhone Simulator; iPhone OS 4.2; en_US)
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif ua.startswith('CoolReader/'):
                # CoolReader/3(Android)
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif 'Freda' in ua:
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1
            elif 'Duokan' in ua:
                format_ = 'opds'
                mediatype = mt.opds
                opensearch_support = 1

        self.format = format_
        self.mediatype = mediatype
        self.opensearch_support = opensearch_support


    def log_request(self, page):
        """ Log the request params. Now a dummy. """
        pass


    def fix_sortorder(self):
        """ Check selected sort order against available sort orders. """

        if self.sort_orders:
            if not self.sort_order or self.sort_order not in self.sort_orders:
                self.sort_order = self.sort_orders [0]

        self.alternate_sort_orders = [x for x in self.sort_orders
                                      if x != self.sort_order]

        self.sorted_by = self.sorted_msgs [self.sort_order]
        self.title += " (%s)" % self.sorted_by

        # content of extra field depends on sorting
        self.f_format_extra = {
            'alpha': self.format_none,
            'author': self.format_none,
            'title': self.format_none,
            'downloads': self.format_downloads,
            'quantity': self.format_quantity,
            'release_date': self.format_release_date,
            'random': self.format_none,
            }[self.sort_order]

        if self.sort_order == 'title':
            self.f_format_title = self.format_title_filing



    @staticmethod
    def format_title(row):
        """ Format a book title for display in results. """
        title = gg.cut_at_newline(row.get('title') or 'No Title')
        for lang_id in row.get('fk_langs') or []:
            if lang_id != 'en':
                title += " (%s)" % language_map.get(lang_id, lang_id)
        return title

    @staticmethod
    def format_title_filing(row):
        """ Format a book title for display in results. """
        title = gg.cut_at_newline(row.get('filing') or 'No Title')
        for lang_id in row.get('fk_langs') or []:
            if lang_id != 'en':
                title += " (%s)" % language_map.get(lang_id, lang_id)
        return title

    @staticmethod
    def format_author(row):
        """ Format an author name for display in results. """
        authors = row.get('author')
        if authors is None:
            return None
        authors = [ DublinCore.DublinCore.make_pretty_name(a) for a in authors ]
        return DublinCore.DublinCore.strunk(authors)

    @staticmethod
    def format_language(row):
        """ Format a language name for display in results. """
        return language_map.get(row.pk, row.pk)

    @staticmethod
    def format_none(dummy_row):
        """ Output nothing on results. """
        return None

    @staticmethod
    def format_subtitle(row):
        """ Format a book subtitle for display in results. """
        return row.get('subtitle')

    @staticmethod
    def format_downloads(row):
        """ Format the no. of download for display in results. """
        downloads = int(row.get('downloads', 0))
        # NOTE: No. of times a book was downloaded
        return __('1 download', '{0} downloads', downloads).format(downloads)

    @staticmethod
    def format_quantity(row):
        """ Format the quantity of books for display in results. """
        count = int(row.get('quantity', 0))
        # NOTE: No. of books by some author, on a subject, etc.
        return __('1 book', '{0} books', count).format(count)

    @staticmethod
    def format_release_date(row):
        """ Format the release date for display in results. """
        return babel.dates.format_date(row.get('release_date'),
                                        locale = str(cherrypy.response.i18n.locale))

    def format_suggestion(self, row):
        """ Format a suggestion for display in results. """
        query = ' '.join(self.query.split()[0:-1])
        if query:
            query += ' '
        return query + gg.cut_at_newline(row.get('title') or '')

    @staticmethod
    def format_no_url(dummy_row):
        """ Show no url in results. """
        return None

    def format_bibrec_url(self, row):
        """ Generate a bibrec url """
        return self.url('bibrec', id = row.pk)

    def format_canonical_bibrec_url(self, row):
        """ Generate the rel=canonical bibrec url for a book. """
        return self.url('bibrec', host=self.file_host, protocol='https', id=row.pk, format=None)

    def format_thumb_url(self, row):
        """ Generate the thumb url in results. """
        if row.coverpages:
            return '/' + row.coverpages[0]
        return None

    def format_icon(self, dummy_row):
        """ Show a book icon in results. """
        return self.icon

    def format_icon_titles(self, row):
        """ Show a book icon or audio icon in results. """
        # for 'title' listings, replace book icon with audio icon
        if row.fk_categories and AUDIOBOOK_CATEGORIES.intersection(row.fk_categories):
            return 'audiobook'
        return self.icon



def sql_get(query, **params):
    """ Quick and dirty SQL query returning one value. """
    conn = cherrypy.engine.pool.connect()
    try:
        c  = conn.cursor()
        c.execute(query, params)
        row = c.fetchone()
        if row:
            return row[0]
        return None
    except DatabaseError as what:
        cherrypy.log("SQL Error: %s\n" % what,
                      context = 'REQUEST', severity = logging.ERROR)
        cherrypy.log("Query was: %s\n" % c.mogrify(query, params),
                      context = 'REQUEST', severity = logging.ERROR)
        conn.detach()
        raise


class SQLSearcher(object):
    """ An SQL searcher. """

    def search(self, os, sql):
        """
        Perform the SQL query and format rows into `Cat´s .

        Use plugin functions to format rows.

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

        for i in range(0, min(len(rows), os.items_per_page)):
            row = rows[i]

            cat = Cat()

            cat.title      = os.f_format_title(row)
            cat.subtitle   = os.f_format_subtitle(row)
            cat.extra      = os.f_format_extra(row)
            cat.url        = os.f_format_url(row)
            cat.thumb_url  = os.f_format_thumb_url(row)
            cat.icon       = os.f_format_icon(row)

            cat.header     = row.get('header', '')

            cat.class_ += os.class_
            cat.order = 10

            os.entries.append(cat)

        return os


    @staticmethod
    def mogrify(dummy_os, sql):
        """ Format a query and return it as string without executing it. """

        conn = cherrypy.engine.pool.connect()
        c  = conn.cursor()
        query, params = sql.build()
        return c.mogrify(query, params).decode('utf-8')


    @staticmethod
    def execute(query, params):
        """ Execute a query and return an array of rows. """

        conn = cherrypy.engine.pool.connect()
        try:
            c  = conn.cursor()

            #cherrypy.log("SQL Query: %s\n" % c.mogrify (query, params),
            #              context = 'REQUEST', severity = logging.ERROR)

            c.execute(query, params)

            return [xl(c, row) for row in c.fetchall()]
        except DatabaseError as what:
            cherrypy.log("SQL Error: %s\n" % what,
                          context = 'REQUEST', severity = logging.ERROR)
            cherrypy.log("Query was: %s\n" % c.mogrify(query, params),
                          context = 'REQUEST', severity = logging.ERROR)
            conn.detach()
            raise
