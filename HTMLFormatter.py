#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: iso-8859-1 -*-

"""
HTMLFormatter.py

Copyright 2009-2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Produce a HTML page.

"""

from __future__ import unicode_literals

import operator

import cherrypy
import genshi.output
import re
import six
from six.moves import urllib

from libgutenberg.MediaTypes import mediatypes as mt

import BaseSearcher
import BaseFormatter
from i18n_tool import ugettext as _

# filetypes ignored on desktop site
NO_DESKTOP_FILETYPES = 'plucker qioo rdf rst rst.gen rst.master tei cover.medium cover.small'.split ()

# filetypes shown on mobile site
MOBILE_TYPES = (mt.epub, mt.mobi, mt.pdf, 'text/html', mt.html)

# filetypes which are usually handed over to a separate app on mobile devices
HANDOVER_TYPES = (mt.epub, mt.mobi, mt.pdf)

# self-contained files we can send to dropbox
CLOUD_TYPES = (mt.epub, mt.mobi, mt.pdf)
STD_PDF_MATCH = re.compile (r'files/\d+/\d+-pdf.pdf$')

class XMLishFormatter (BaseFormatter.BaseFormatter):
    """ Produce XMLish output. """

    def __init__ (self):
        super (XMLishFormatter, self).__init__ ()


    def fix_dc (self, dc, os):
        """ Tweak dc. """
        def has_std_path (file_obj):
            ''' so cloudstorage links can be elided when the url is non-standard'''
            if file_obj.filetype == 'pdf':
                return STD_PDF_MATCH.search (file_obj.url)
            return True

        super (XMLishFormatter, self).fix_dc (dc, os)

        # generated_files always [] AFAICT -esh
        for file_ in dc.generated_files:
            file_.help_topic = file_.hr_filetype
            file_.compression = 'none'
            file_.encoding  = None

        dedupable = {}
        for file_ in dc.files:
            if file_.filetype and file_.filetype.endswith('images'):
                dedupable[file_.filetype] = file_
        do_dedupe = False
        for ft in ['epub', 'kindle', 'pdf']:
            if ft + '.images' in dedupable and ft + '.noimages' in dedupable:
                if dedupable[ft + '.images'].extent == dedupable[ft + '.noimages'].extent:
                    do_dedupe = True
        if do_dedupe:
            for ft in ['epub', 'kindle', 'pdf']:
                if ft + '.images' in dedupable and ft + '.noimages' in dedupable:
                    dc.files.remove(dedupable[ft + '.images'])
                
        for file_ in dc.files + dc.generated_files:
            type_ = six.text_type (file_.mediatypes[0])
            m = type_.partition (';')[0]
            if m in CLOUD_TYPES and has_std_path (file_):
                file_.dropbox_url = os.url (
                    'dropbox_send', id = dc.project_gutenberg_id, filetype = file_.filetype)
                file_.gdrive_url = os.url (
                    'gdrive_send', id = dc.project_gutenberg_id, filetype = file_.filetype)
                file_.msdrive_url = os.url (
                    'msdrive_send', id = dc.project_gutenberg_id, filetype = file_.filetype)

            # these are used as relative links
            if file_.generated and not file_.filetype.startswith ('cover.'):
                file_.filename = "ebooks/%d.%s" % (dc.project_gutenberg_id, file_.filetype)
                if m in HANDOVER_TYPES:
                    file_.filename = file_.filename + '?' + urllib.parse.urlencode (
                        { 'session_id': str (cherrypy.session.id) } )

        for file_ in dc.files:
            file_.honeypot_url = os.url (
                'honeypot_send', id = dc.project_gutenberg_id, filetype = file_.filetype)
            break


    def format (self, page, os):
        """ Format to HTML. """

        for e in os.entries:
            if isinstance (e, BaseSearcher.DC):
                self.fix_dc (e, os)

        # loop again because fix:dc appends things
        for e in os.entries:
            if isinstance (e, BaseSearcher.Cat):
                if e.url:
                    e.icon2 = e.icon2 or 'next'
                else:
                    e.class_ += 'grayed'

        if os.title_icon:
            os.class_ += 'icon_' + os.title_icon

        os.entries.sort (key = operator.attrgetter ('order'))

        return self.render (page, os)


class HTMLFormatter (XMLishFormatter):
    """ Produce HTML output. """

    CONTENT_TYPE = 'text/html; charset=UTF-8'
    DOCTYPE      = 'html5'

    def __init__ (self):
        super (HTMLFormatter, self).__init__ ()


    def get_serializer (self):
        # return BaseFormatter.XHTMLSerializer (doctype = self.DOCTYPE, strip_whitespace = False)
        return genshi.output.HTMLSerializer (doctype = self.DOCTYPE, strip_whitespace = False)


    def fix_dc (self, dc, os):
        """ Add some info to dc for easier templating.

        Also make sure that dc `walks like a cat´. """

        super (HTMLFormatter, self).fix_dc (dc, os)

        #for author in dc.authors:
        #    author.authors_page_url = (
        #        "/browse/authors/%s#a%d" % (author.name[:1].lower (), author.id))
        if dc.new_filesystem:
            dc.base_dir = "/files/%d/" % dc.project_gutenberg_id
            # dc.mirror_dir = gg.archive_dir (dc.project_gutenberg_id)
        else:
            dc.base_dir = None
            # dc.mirror_dir = None

        dc.magnetlink = None

        # hide all txt files but the first one
        txtcount = showncount = 0

        for file_ in dc.files + dc.generated_files:
            filetype = file_.filetype or ''
            file_.hidden = False

            if filetype in NO_DESKTOP_FILETYPES:
                file_.hidden = True
            if file_.compression != 'none':
                file_.hidden = True
            if filetype.startswith ('txt'):
                if txtcount > 0:
                    file_.hidden = True
                txtcount += 1
            if filetype != 'txt':
                file_.encoding = None
            if file_.encoding:
                file_.hr_filetype += ' ' + file_.encoding.upper ()
            if filetype.startswith ('html') and file_.compression == 'none':
                file_.hr_filetype = 'Read this book online: {}'.format (file_.hr_filetype)
            if not file_.hidden:
                showncount += 1

        # if we happened to hide everything, show all files
        if showncount == 0:
            for file_ in dc.files + dc.generated_files:
                file_.hidden = False


class MobileFormatter (XMLishFormatter):
    """ Produce HTML output suitable for mobile devices. """

    CONTENT_TYPE = mt.xhtml + '; charset=UTF-8'
    DOCTYPE      = 'html5'

    def __init__ (self):
        super (MobileFormatter, self).__init__ ()


    def get_serializer (self):
        return genshi.output.HTMLSerializer (doctype = self.DOCTYPE, strip_whitespace = False)


    def fix_dc (self, dc, os):
        """ Add some info to dc for easier templating.

        Also make sure that dc `walks like a cat´. """

        super (MobileFormatter, self).fix_dc (dc, os)

        for file_ in dc.files + dc.generated_files:
            if len (file_.mediatypes) == 1:
                type_ = six.text_type (file_.mediatypes[0])
                m = type_.partition (';')[0]
                if m in MOBILE_TYPES:
                    cat = BaseSearcher.Cat ()
                    cat.type = file_.mediatypes[0]
                    cat.header = _('Download')
                    cat.title = file_.hr_filetype
                    cat.extra = file_.hr_extent

                    cat.charset = file_.encoding
                    cat.url = '/' + file_.filename
                    cat.icon = dc.icon
                    cat.icon2 = 'download'
                    cat.class_ += 'filelink'
                    cat.order = 20
                    os.entries.append (cat)
