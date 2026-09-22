#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
MyShelvesPage.py

Copyright 2026 by Project Gutenberg

Distributable under the GNU General Public License Version 3 or newer.

"""

from __future__ import unicode_literals

import BaseSearcher
import Page
from i18n_tool import ugettext as _


class MyShelvesPage(Page.Page):
    """ Bookshelves stored in the browser. """

    def index(self, **dummy_kwargs):
        os_ = BaseSearcher.OpenSearch()
        os_.title = _('My bookshelves')
        os_.description = _('Bookshelves kept in this browser.')
        os_.template = 'myshelves'
        os_.page = 'myshelves'
        os_.finalize()
        return self.format(os_)
