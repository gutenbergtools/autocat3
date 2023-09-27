#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
OPDSFormatter.py

Copyright 2009-2012 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Produce an OPDS feed.

"""

from __future__ import unicode_literals

import copy
import re

import genshi.output
import cherrypy
import six

from libgutenberg.GutenbergGlobals import Struct, xmlspecialchars
from libgutenberg.MediaTypes import mediatypes as mt
from libgutenberg import DublinCore

import BaseFormatter
from Icons import THUMBS as th


# files a mobile can download
OPDS_TYPES = (mt.epub, mt.mobi, mt.pdf)

# domains allowed to XMLHttpRequest () our OPDS feed
CORS_DOMAINS = '*'

class OPDSFormatter (BaseFormatter.BaseFormatter):
    """ Produces opds output. """

    CONTENT_TYPE = mt.opds + '; charset=UTF-8'
    DOCTYPE      = None


    def get_serializer (self):
        return genshi.output.XMLSerializer (doctype = self.DOCTYPE, strip_whitespace = False)


    def send_headers (self):
        """ Send HTTP content-type header. """

        cherrypy.response.headers['Access-Control-Allow-Origin'] = CORS_DOMAINS
        super (OPDSFormatter, self).send_headers ()


    def format (self, page, os):
        """ Format os struct into opds output. """

        entries = []
        for dc in os.entries:
            dc.thumbnail = None
            if isinstance (dc, DublinCore.DublinCore):
                dc.image_flags = 0
                if dc.has_images ():
                    dc.pool = None
                    dc_copy = copy.deepcopy (dc)

                    dc.image_flags = 2
                    dc.icon = 'title_no_images'
                    self.fix_dc (dc, os)
                    entries.append (dc)

                    dc_copy.image_flags = 3
                    self.fix_dc (dc_copy, os, True)
                    entries.append (dc_copy)
                else:
                    self.fix_dc (dc, os)
                    entries.append (dc)
            else:
                # actually not a dc
                # throw out 'start over' link, FIXME: actually throw out all non-dc's ?
                if page == 'bibrec' and dc.rel == 'start':
                    continue
                dc.links = []
                if dc.icon in th:
                    link = Struct ()
                    link.type = mt.png
                    link.rel = 'thumb'
                    link.url = self.data_url (th[dc.icon])
                    link.title = None
                    link.length = None
                    dc.links.append (link)

                entries.append (dc)

        os.entries = entries

        if page == 'bibrec':
            # we have just one template for both
            page = 'results'

        return self.render (page, os)


    def fix_dc (self, dc, os, want_images = False):
        """ Make fixes to dublincore struct. """

        def to_html (text):
            """ Turn plain text into html. """
            return re.sub (r'[\r\n]+', '<br/>', xmlspecialchars (text))

        def key_role (author):
            """ Sort authors first, then other contributors. """
            if author.marcrel in ('cre', 'aut'):
                return ''
            return author.marcrel

        super (OPDSFormatter, self).fix_dc (dc, os)

        if dc.icon in th:
            dc.thumbnail = self.data_url (th[dc.icon])

        dc.links = []

        dc.title_html = to_html (dc.title)

        dc.authors.sort (key = key_role)

        for file_ in dc.files:
            if len (file_.mediatypes) == 1:
                type_ = six.text_type (file_.mediatypes[0])
                filetype = file_.filetype or ''

                if type_.partition (';')[0] in OPDS_TYPES:
                    if ((filetype.find ('.images') > -1) == want_images):
                        link = Struct ()
                        link.type = type_
                        link.title = file_.hr_filetype
                        link.url = file_.url
                        link.length = str (file_.extent)
                        link.rel = 'acquisition'
                        dc.links.append (link)

                if filetype == 'cover.small':
                    link = Struct ()
                    link.type = six.text_type (file_.mediatypes[0])
                    link.title = None
                    link.url = file_.url
                    link.length = None
                    link.rel = 'thumb'
                    dc.links.append (link)

                if filetype == 'cover.medium':
                    link = Struct ()
                    link.type = six.text_type (file_.mediatypes[0])
                    link.title = None
                    link.url = file_.url
                    link.length = None
                    link.rel = 'cover'
                    dc.links.append (link)
