#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
Formatters.py

Copyright 2009-2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Formatters for all mediatypes.

"""

from __future__ import unicode_literals

import glob
import logging
import os.path

import genshi.template
import genshi.filters

import cherrypy

import HTMLFormatter
import OPDSFormatter
import JSONFormatter

def format (format_, page, os_):
    """ Main entry point. """

    return formatters[format_].format (page, os_)


formatters = {}
formatters['opds']     = OPDSFormatter.OPDSFormatter   ()
formatters['stanza']   = formatters['opds']
formatters['mobile']   = HTMLFormatter.MobileFormatter ()
formatters['html']     = HTMLFormatter.HTMLFormatter   ()
formatters['json']     = JSONFormatter.JSONFormatter   ()
# FIXME: only needed to load sitemap.xml templates
formatters['xml']      = HTMLFormatter.XMLishFormatter ()

def on_template_loaded (template):
    """
    Callback.

    We need to use the callback because we are using includes.
    The callback will also setup () the includes.

    """

    genshi.filters.Translator (_).setup (template)


def init ():
    """ Load all template files in template_dir. """

    template_dir = cherrypy.config['genshi.template_dir']

    for fn in glob.glob (os.path.join (template_dir, '*')):
        if fn.endswith ('~') or fn.endswith ('#') or fn.endswith ('schemas.xml'):
            # backup file or emacs temp file
            continue

        cherrypy.engine.autoreload.files.update (fn)

        bn = os.path.basename (fn)
        template = genshi.template.TemplateLoader (
            template_dir,
            callback = on_template_loaded).load (bn)

        page, dot_format = os.path.splitext (bn)

        formatters[dot_format[1:]].set_template (page, template)

        cherrypy.log ("Template '%s' loaded." % fn,
                      context = 'GENSHI', severity = logging.INFO)
