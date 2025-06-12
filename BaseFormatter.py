#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
BaseFormatter.py

Copyright 2009-2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Base class for output formatters.

"""

from __future__ import unicode_literals

import base64
import datetime
import os
import re
from six.moves import urllib

from genshi.core import _ensure
from genshi.core import escape, Markup, QName
from genshi.core import START, END, TEXT, XML_DECL, DOCTYPE, START_CDATA, END_CDATA, PI, COMMENT
import genshi.output
from genshi.output import EMPTY, EmptyTagFilter, WhitespaceFilter, \
                          NamespaceFlattener, DocTypeInserter
import genshi.template


import cherrypy

from libgutenberg import GutenbergGlobals as gg

import BaseSearcher

# use a bit more aggressive whitespace removal than the standard whitespace filter
COLLAPSE_LINES = re.compile('\n[ \t\r\n]+').sub

WHITESPACE_FILTER = genshi.output.WhitespaceFilter()

DATA_URL_CACHE = {}

class BaseFormatter(object):
    """ Base class for formatters. """

    CONTENT_TYPE = 'text/html; charset=UTF-8'

    def __init__(self):
        self.templates = {}


    def format(self, page, os):
        """ Abstract method to override. """
        pass


    def get_serializer(self):
        """ Abstract method to override.

        Like this:
        return genshi.output.XMLSerializer(doctype = self.DOCTYPE, strip_whitespace = False)

        """
        pass


    def send_headers(self):
        """ Send HTTP content-type header. """
        cherrypy.response.headers['Content-Type'] = self.CONTENT_TYPE


    def render(self, page, os, instance_filter=None):
        """ Render and send to browser. """

        self.send_headers()

        template = self.templates[page]
        ctxt = genshi.template.Context(cherrypy=cherrypy, os=os, bs=BaseSearcher)

        stream = template.stream
        for filter_ in template.filters:
            stream = filter_(iter(stream), ctxt)
        if instance_filter:
            stream = instance_filter(stream)


        # there's no easy way in genshi to pass collapse_lines to this filter
        stream = WHITESPACE_FILTER(stream, collapse_lines=COLLAPSE_LINES)

        return genshi.output.encode(self.get_serializer()(_ensure(genshi.Stream(stream))),
                                     encoding='utf-8')


    def set_template(self, page, template):
        """ Set template for page.

        Override this for special handling of template, like adding filters. """
        self.templates[page] = template


    @staticmethod
    def format_date(date):
        """ Format a date. """

        if date is None:
            return ''

        try:
            # datetime
            return date.replace(tzinfo=gg.UTC(), microsecond=0).isoformat()
        except TypeError:
            # date
            return datetime.datetime.combine(
                date, datetime.time(tzinfo=gg.UTC())).isoformat()

    @staticmethod
    def data_url(path):
        """ Read and convert a file to a data url. """
        if path in DATA_URL_CACHE:
            return DATA_URL_CACHE[path]

        abs_path = os.path.join('https://' + cherrypy.config['file_host'], path.lstrip('/'))
        data_url = abs_path
        try:
            f = urllib.request.urlopen(abs_path)
            retcode = f.getcode()
            if retcode is None or retcode == 200:
                msg = f.info()
                mediatype = msg.get('Content-Type')
                if mediatype:
                    mediatype = mediatype.partition(';')[0]
                    data_url = ('data:' + mediatype + ';base64,' +
                                base64.b64encode(f.read()).decode('ascii'))
            f.close()
        except IOError:
            pass

        DATA_URL_CACHE[path] = data_url
        return data_url


    def fix_dc(self, dc, os):
        """ Add some info to dc for easier templating. """

        # obsolete private marc codes for cover art
        dc.marcs = [ marc for marc in dc.marcs if (
            not marc.code.startswith('9') or marc.code == '908')
        ]

        dc.cover_image = None
        dc.cover_thumb = None
        # cover image really should not be a property of opensearch,
        # but it is accessed in many places and this way we can save a
        # lot of iterations later
        os.cover_image_url = None
        os.cover_thumb_url = None

        for file_ in dc.files:

            # HACK for https://
            if file_.url.startswith('http://'):
                file_.url = 'https' + file_.url[4:]

            file_.dropbox_url = None
            # file_.dropbox_filename = None
            file_.gdrive_url = None
            file_.msdrive_url = None

            if file_.filetype == 'cover.medium':
                dc.cover_image = file_
                os.snippet_image_url = os.cover_image_url = file_.url
            elif file_.filetype == 'cover.small':
                dc.cover_thumb = file_
                os.cover_thumb_url = file_.url

            dc.xsd_release_date_time = self.format_date(dc.release_date)

        if 'Sound' in dc.categories:
            dc.icon = 'audiobook'


# lifted from genshi/output.py and fixed lang issue
# lang is not allowed in xhtml 1.1 which we must use
# because xhtml+rdfa is based on it

class XHTMLSerializer(genshi.output.XMLSerializer):
    """Produces XHTML text from an event stream.

    >>> from genshi.builder import tag
    >>> elem = tag.div(tag.a(href='foo'), tag.br, tag.hr(noshade=True))
    >>> print(''.join(XHTMLSerializer()(elem.generate())))
    <div><a href="foo"></a><br /><hr noshade="noshade" /></div>
    """

    _EMPTY_ELEMS = frozenset(['area', 'base', 'basefont', 'br', 'col', 'frame',
                              'hr', 'img', 'input', 'isindex', 'link', 'meta',
                              'param'])
    _BOOLEAN_ATTRS = frozenset(['selected', 'checked', 'compact', 'declare',
                                'defer', 'disabled', 'ismap', 'multiple',
                                'nohref', 'noresize', 'noshade', 'nowrap'])
    _PRESERVE_SPACE = frozenset([
        QName('pre'), QName('http://www.w3.org/1999/xhtml}pre'),
        QName('textarea'), QName('http://www.w3.org/1999/xhtml}textarea')
    ])

    def __init__(self, doctype=None, strip_whitespace=True,
                 namespace_prefixes=None, drop_xml_decl=True, cache=True):
        super(XHTMLSerializer, self).__init__(doctype, False)
        self.filters = [EmptyTagFilter()]
        if strip_whitespace:
            self.filters.append(WhitespaceFilter(self._PRESERVE_SPACE))
        namespace_prefixes = namespace_prefixes or {}
        namespace_prefixes['http://www.w3.org/1999/xhtml'] = ''
        self.filters.append(NamespaceFlattener(prefixes=namespace_prefixes,
                                               cache=cache))
        if doctype:
            self.filters.append(DocTypeInserter(doctype))
        self.drop_xml_decl = drop_xml_decl
        self.cache = cache

    def __call__(self, stream):
        boolean_attrs = self._BOOLEAN_ATTRS
        empty_elems = self._EMPTY_ELEMS
        drop_xml_decl = self.drop_xml_decl
        have_decl = have_doctype = False
        in_cdata = False

        cache = {}
        cache_get = cache.get
        if self.cache:
            def _emit(kind, input, output):
                cache[kind, input] = output
                return output
        else:
            def _emit(kind, input, output):
                return output

        for filter_ in self.filters:
            stream = filter_(stream)
        for kind, data, pos in stream:
            cached = cache_get((kind, data))
            if cached is not None:
                yield cached

            elif kind is START or kind is EMPTY:
                tag, attrib = data
                buf = ['<', tag]
                for attr, value in attrib:
                    if attr in boolean_attrs:
                        value = attr
                    # this is the fix
                    # elif attr == 'xml:lang' and 'lang' not in attrib:
                    #     buf += [' lang="', escape(value), '"']
                    elif attr == 'xml:space':
                        continue
                    buf += [' ', attr, '="', escape(value), '"']
                if kind is EMPTY:
                    if tag in empty_elems:
                        buf.append(' />')
                    else:
                        buf.append('></%s>' % tag)
                else:
                    buf.append('>')
                yield _emit(kind, data, Markup(''.join(buf)))

            elif kind is END:
                yield _emit(kind, data, Markup('</%s>' % data))

            elif kind is TEXT:
                if in_cdata:
                    yield _emit(kind, data, data)
                else:
                    yield _emit(kind, data, escape(data, quotes=False))

            elif kind is COMMENT:
                yield _emit(kind, data, Markup('<!--%s-->' % data))

            elif kind is DOCTYPE and not have_doctype:
                name, pubid, sysid = data
                buf = ['<!DOCTYPE %s']
                if pubid:
                    buf.append(' PUBLIC "%s"')
                elif sysid:
                    buf.append(' SYSTEM')
                if sysid:
                    buf.append(' "%s"')
                buf.append('>\n')
                yield Markup(''.join(buf)) % tuple([p for p in data if p])
                have_doctype = True

            elif kind is XML_DECL and not have_decl and not drop_xml_decl:
                version, encoding, standalone = data
                buf = ['<?xml version="%s"' % version]
                if encoding:
                    buf.append(' encoding="%s"' % encoding)
                if standalone != -1:
                    standalone = standalone and 'yes' or 'no'
                    buf.append(' standalone="%s"' % standalone)
                buf.append('?>\n')
                yield Markup(''.join(buf))
                have_decl = True

            elif kind is START_CDATA:
                yield Markup('<![CDATA[')
                in_cdata = True

            elif kind is END_CDATA:
                yield Markup(']]>')
                in_cdata = False

            elif kind is PI:
                yield _emit(kind, data, Markup('<?%s %s?>' % data))
