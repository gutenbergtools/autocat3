#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
TemplatedPage.py

Copyright 2013 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Output a Genshi page.

"""

from __future__ import unicode_literals

import genshi.output
import genshi.template
from genshi.core import _ensure
import cherrypy

import Formatters
import BaseSearcher


class TemplatedPage (object):
    """ Output a page from a genshi template. """

    CONTENT_TYPE = 'application/xml; charset=UTF-8'
    FORMATTER = 'xml'


    def get_serializer (self):
        """ Override to get a different serializer. """

        return genshi.output.XMLSerializer (strip_whitespace = False)


    def output (self, template, **kwargs):
        """ Output the page. """

        # Send HTTP content-type header.
        cherrypy.response.headers['Content-Type'] = self.CONTENT_TYPE

        template = Formatters.formatters[self.FORMATTER].templates[template]
        ctxt = genshi.template.Context (cherrypy = cherrypy, bs = BaseSearcher, **kwargs)

        stream = template.stream
        for filter_ in template.filters:
            stream = filter_ (iter (stream), ctxt)

        serializer = self.get_serializer ()

        return genshi.output.encode (serializer (
                _ensure (genshi.Stream (stream))), encoding = 'utf-8')


class TemplatedPageXHTML (TemplatedPage):
    """ Output a page from a genshi template. """

    CONTENT_TYPE = 'text/html; charset=UTF-8'
    FORMATTER    = 'html'
    DOCTYPE      = ('html',
                    '-//W3C//DTD XHTML 1.0 Strict//EN',
                    'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd')

    def get_serializer (self):
        return genshi.output.XHTMLSerializer (doctype = self.DOCTYPE, strip_whitespace = False)
