#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""

DublinCoreI18n.py

Copyright 2009-2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Translate a DublinCore struct with Babel.

"""

from __future__ import unicode_literals

import cherrypy
import babel
from i18n_tool import ugettext as _

class DublinCoreI18nMixin (object):
    """ Translator Mixin for GutenbergDatabaseDublinCore class. """

    def __init__ (self):
        self.translated = False
        self.hr_release_date = None
        self.rights = None


    @staticmethod
    def dummy_text_holder ():
        """Never gets called.

        Only holds some gettext messages to translate.  Keep this in
        sync with GutenbergDatabaseDublinCore.

        """
        _('Copyrighted. Read the copyright notice inside this book for details.')
        _('Public domain in the USA.')


    def translate (self):
        """ Translate DublinCore struct. """

        if self.translated:
            # already translated
            return

        self.hr_release_date = babel.dates.format_date (
            self.release_date, locale = str (cherrypy.response.i18n.locale))

        if cherrypy.response.i18n.locale.language == 'en':
            # no translation required
            return

        self.rights = _(self.rights)
        for author in self.authors:
            author.role = _(author.role)
        for marc in self.marcs:
            marc.caption = _(marc.caption)
        for dcmitype in self.dcmitypes:
            dcmitype.description = _(dcmitype.description)
        for lang in self.languages:
            if lang.id in cherrypy.response.i18n.locale.languages:
                lang.language = cherrypy.response.i18n.locale.languages[lang.id].capitalize ()
        for file_ in self.files:
            file_.hr_filetype = _(file_.hr_filetype)

        self.translated = True
