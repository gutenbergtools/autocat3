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
import genshi.output
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
