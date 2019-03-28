#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
JSONFormatter.py

Copyright 2009-2012 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Produce a JSON response.

"""

from __future__ import unicode_literals

import json
import re

from libgutenberg.MediaTypes import mediatypes as mt

import BaseFormatter

RE_WORD = re.compile (r'\W+', re.U)

class JSONFormatter (BaseFormatter.BaseFormatter):
    """ Produce JSON output. """

    CONTENT_TYPE = mt.json + '; charset=UTF-8'
    CONTENT_TYPE = 'application/json; charset=UTF-8'
    DOCTYPE = None

    def __init__ (self):
        super (JSONFormatter, self).__init__ ()


    def format (self, dummy_page, os):

        # Specs:
        # http://www.opensearch.org/Specifications/OpenSearch/Extensions/Suggestions/1.0

        sugg0 = []
        sugg1 = []
        sugg2 = []

        for e in os.entries:
            if 'navlink' not in e.class_:
                sugg0.append (e.title)
                sugg1.append (e.subtitle)
                sugg2.append (e.url)

        self.send_headers ()
        return json.dumps ( [os.query, sugg0, sugg1, sugg2] ).encode ('utf-8')
