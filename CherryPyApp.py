#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CherryPyApp.py

Copyright 2009-2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The Project Gutenberg Catalog App Server.

Config and route setup.

"""

from __future__ import unicode_literals

import logging
import logging.handlers # rotating file handler
import os
import time
import traceback

import cherrypy
from cherrypy.process import plugins
import six
from six.moves import builtins

from libgutenberg import GutenbergDatabase

import i18n_tool
# Make translator functions available everywhere. Do this early, at
# least before Genshi starts loading templates.
builtins._     = i18n_tool.ugettext
builtins.__    = i18n_tool.ungettext

import ConnectionPool
import Page
import StartPage
import SuggestionsPage
from SearchPage import BookSearchPage, AuthorSearchPage, SubjectSearchPage, BookshelfSearchPage, \
    AuthorPage, SubjectPage, BookshelfPage, AlsoDownloadedPage
from BibrecPage import BibrecPage
import CoverPages
import QRCodePage
import StatsPage
import CaptchaPage
import Sitemap
import Formatters
import RateLimiter

import Timer
import MyRamSession
import PostgresSession

cherrypy.lib.sessions.RamSession      = MyRamSession.FixedRamSession
cherrypy.lib.sessions.MyramSession    = MyRamSession.MyRamSession
cherrypy.lib.sessions.PostgresSession = PostgresSession.PostgresSession

plugins.Timer = Timer.TimerPlugin

if six.PY3:
    CHERRYPY_CONFIG = ('/etc/autocat3.conf', os.path.expanduser ('~/.autocat3'))
    # CCHERRYPY_CONFIG = ('/etc/autocat3.conf')
else:
    CHERRYPY_CONFIG = ('/etc/autocat.conf', os.path.expanduser ('~/.autocat'))

class MyRoutesDispatcher (cherrypy.dispatch.RoutesDispatcher):
    """ Dispatcher that tells us the matched route.

    CherryPy makes it hard for us by forgetting the matched route object.
    Here we add a 'route_name' parameter, that will tell us the route's name.

    """

    def connect (self, name, route, controller, **kwargs):
        """ Add a 'route_name' parameter that will tell us the matched route. """
        kwargs['route_name'] = name
        kwargs.setdefault ('action', 'index')
        cherrypy.dispatch.RoutesDispatcher.connect (self, name, route, controller, **kwargs)


def main ():
    """ Main function. """

    # default config
    cherrypy.config.update ({
        'uid': 0,
        'gid': 0,
        'server_name': 'localhost',
        'genshi.template_dir': os.path.join (
            os.path.dirname (os.path.abspath (__file__)), 'templates'),
        'daemonize': False,
        'pidfile': None,
        'host': 'localhost',
        'host_mobile': 'localhost',
        'file_host': 'localhost',
        })

    config_filename = None
    for config_filename in CHERRYPY_CONFIG:
        try:
            cherrypy.config.update (config_filename)
            break
        except IOError:
            pass

    # Rotating Logs
    #

    # Remove the default FileHandlers if present.

    error_file = cherrypy.log.error_file
    access_file = cherrypy.log.access_file
    cherrypy.log.error_file = ""
    cherrypy.log.access_file = ""

    max_bytes = getattr (cherrypy.log, "rot_max_bytes", 100 * 1024 * 1024)
    backup_count = getattr (cherrypy.log, "rot_backup_count", 2)
    #print(os.path.abspath(error_file)+": Filehandler cherrypy")
    h = logging.handlers.RotatingFileHandler (error_file, 'a', max_bytes, backup_count, 'utf-8')
    h.setLevel (logging.DEBUG)
    h.setFormatter (cherrypy._cplogging.logfmt)
    cherrypy.log.error_log.addHandler (h)

    h = logging.handlers.RotatingFileHandler (access_file, 'a', max_bytes, backup_count, 'utf-8')
    h.setLevel (logging.DEBUG)
    h.setFormatter (cherrypy._cplogging.logfmt)
    cherrypy.log.access_log.addHandler (h)

    if not cherrypy.config['daemonize']:
        ch = logging.StreamHandler ()
        ch.setLevel (logging.DEBUG)
        ch.setFormatter (cherrypy._cplogging.logfmt)
        cherrypy.log.error_log.addHandler (ch)

    # continue app init
    #

    cherrypy.log ('*' * 80, context = 'ENGINE', severity = logging.INFO)
    cherrypy.log ("Using config file '%s'." % config_filename,
                  context = 'ENGINE', severity = logging.INFO)

    # after cherrypy.config is parsed
    Formatters.init ()
    cherrypy.log ("Continuing App Init", context = 'ENGINE', severity = logging.INFO)

    try:
        cherrypy.tools.rate_limiter = RateLimiter.RateLimiterTool ()
    except Exception as e:
        tb = traceback.format_exc ()
        cherrypy.log (tb, context = 'ENGINE', severity = logging.ERROR)

    cherrypy.log ("Continuing App Init", context = 'ENGINE', severity = logging.INFO)
    cherrypy.tools.I18nTool = i18n_tool.I18nTool ()

    cherrypy.log ("Continuing App Init", context = 'ENGINE', severity = logging.INFO)

    # Used to bust the cache on js and css files.  This should be the
    # files' mtime, but the files are not stored on the app server.
    # This is a `good enough´ replacement though.
    t = str (int (time.time ()))
    cherrypy.config['css_mtime'] = t
    cherrypy.config['js_mtime']  = t

    cherrypy.config['all_hosts'] = (
        cherrypy.config['host'], cherrypy.config['host_mobile'], cherrypy.config['file_host'])

    if hasattr (cherrypy.engine, 'signal_handler'):
        cherrypy.engine.signal_handler.subscribe ()

    cherrypy.engine.pool = plugins.ConnectionPool (
        cherrypy.engine, params = GutenbergDatabase.get_connection_params (cherrypy.config))
    cherrypy.engine.pool.subscribe ()

    plugins.RateLimiterReset (cherrypy.engine).subscribe ()
    plugins.RateLimiterDatabase (cherrypy.engine).subscribe ()
    plugins.Timer (cherrypy.engine).subscribe ()

    cherrypy.log ("Daemonizing", context = 'ENGINE', severity = logging.INFO)

    if cherrypy.config['daemonize']:
        plugins.Daemonizer (cherrypy.engine).subscribe ()

    uid = cherrypy.config['uid']
    gid = cherrypy.config['gid']
    if uid > 0 or gid > 0:
        plugins.DropPrivileges (cherrypy.engine, uid = uid, gid = gid, umask = 0o22).subscribe ()

    if cherrypy.config['pidfile']:
        pid = plugins.PIDFile (cherrypy.engine, cherrypy.config['pidfile'])
        # Write pidfile after privileges are dropped (prio == 77)
        # or we will not be able to remove it.
        cherrypy.engine.subscribe ('start', pid.start, 78)
        cherrypy.engine.subscribe ('exit', pid.exit, 78)


    cherrypy.log ("Setting up routes", context = 'ENGINE', severity = logging.INFO)

    # setup 'routes' dispatcher
    #
    # d = cherrypy.dispatch.RoutesDispatcher (full_result = True)
    d = MyRoutesDispatcher (full_result = True)
    cherrypy.routes_mapper = d.mapper

    def check_id (environ, result):
        """ Check if id is a valid number. """
        try:
            return str (int (result['id'])) == result['id']
        except:
            return False

    d.connect ('start', r'/ebooks{.format}/',
               controller = StartPage.Start ())

    d.connect ('suggest', r'/ebooks/suggest{.format}/',
               controller = SuggestionsPage.Suggestions ())

    # search pages

    d.connect ('search', r'/ebooks/search{.format}/',
               controller = BookSearchPage ())

    d.connect ('author_search', r'/ebooks/authors/search{.format}/',
               controller = AuthorSearchPage ())

    d.connect ('subject_search', r'/ebooks/subjects/search{.format}/',
               controller = SubjectSearchPage ())

    d.connect ('bookshelf_search', r'/ebooks/bookshelves/search{.format}/',
               controller = BookshelfSearchPage ())

    # 'id' pages

    d.connect ('author', r'/ebooks/author/{id:\d+}{.format}',
               controller = AuthorPage (), conditions = dict (function = check_id))

    d.connect ('subject', r'/ebooks/subject/{id:\d+}{.format}',
               controller = SubjectPage (), conditions = dict (function = check_id))

    d.connect ('bookshelf', r'/ebooks/bookshelf/{id:\d+}{.format}',
               controller = BookshelfPage (), conditions = dict (function = check_id))

    d.connect ('also', r'/ebooks/{id:\d+}/also/{.format}',
               controller = AlsoDownloadedPage (), conditions = dict (function = check_id))

    # bibrec pages

    d.connect ('download', r'/ebooks/{id:\d+}/download{.format}',
               controller = Page.NullPage (), _static = True)

    d.connect ('bibrec', r'/ebooks/{id:\d+}{.format}',
               controller = BibrecPage (), conditions = dict (function = check_id))


    # legacy compatibility with /ebooks/123.bibrec
    d.connect ('bibrec2', r'/ebooks/{id:\d+}.bibrec{.format}',
               controller = BibrecPage (), conditions = dict (function = check_id))

    d.connect ('cover', r'/covers/{size:small|medium}/{order:latest|popular}/{count}',
               controller = CoverPages.CoverPages ())

    d.connect ('qrcode', r'/qrcode/',
               controller = QRCodePage.QRCodePage ())

    d.connect ('iplimit', r'/iplimit/',
               controller = Page.NullPage ())

    d.connect ('stats', r'/stats/',
               controller = StatsPage.StatsPage ())

    d.connect ('block', r'/stats/block/',
               controller = RateLimiter.BlockPage ())

    d.connect ('unblock', r'/stats/unblock/',
               controller = RateLimiter.UnblockPage ())

    d.connect ('traceback', r'/stats/traceback/',
               controller = RateLimiter.TracebackPage ())

    d.connect ('honeypot_send', r'/ebooks/send/megaupload/{id:\d+}.{filetype}',
               controller = Page.NullPage (), _static = True)

    # /w/captcha/question/ so varnish will cache it
    d.connect ('captcha.question', r'/w/captcha/question/',
               controller = CaptchaPage.QuestionPage ())

    d.connect ('captcha.answer', r'/w/captcha/answer/',
               controller = CaptchaPage.AnswerPage ())

    # sitemap protocol access control requires us to place sitemaps in /ebooks/
    d.connect ('sitemap', r'/ebooks/sitemaps/',
               controller = Sitemap.SitemapIndex ())

    d.connect ('sitemap_index', r'/ebooks/sitemaps/{page:\d+}',
               controller = Sitemap.Sitemap ())

    if 'dropbox_client_id' in cherrypy.config:
        import Dropbox
        dropbox = Dropbox.Dropbox ()
        cherrypy.log ("Dropbox Client Id: %s" % cherrypy.config['dropbox_client_id'],
                      context = 'ENGINE', severity = logging.INFO)
        d.connect ('dropbox_send', r'/ebooks/send/dropbox/{id:\d+}.{filetype}',
                   controller = dropbox, conditions = dict (function = check_id))
        d.connect ('dropbox_callback', r'/ebooks/send/dropbox/',
                   controller = dropbox)

    if 'gdrive_client_id' in cherrypy.config:
        import GDrive
        gdrive = GDrive.GDrive ()
        cherrypy.log ("GDrive Client Id: %s" % cherrypy.config['gdrive_client_id'],
                      context = 'ENGINE', severity = logging.INFO)
        d.connect ('gdrive_send', r'/ebooks/send/gdrive/{id:\d+}.{filetype}',
                   controller = gdrive, conditions = dict (function = check_id))
        d.connect ('gdrive_callback', r'/ebooks/send/gdrive/',
                   controller = gdrive)

    if 'msdrive_client_id' in cherrypy.config:
        import MSDrive
        msdrive = MSDrive.MSDrive ()
        cherrypy.log ("MSDrive Client Id: %s" % cherrypy.config['msdrive_client_id'],
                      context = 'ENGINE', severity = logging.INFO)
        d.connect ('msdrive_send', r'/ebooks/send/msdrive/{id:\d+}.{filetype}',
                   controller = msdrive, conditions = dict (function = check_id))
        d.connect ('msdrive_callback', r'/ebooks/send/msdrive/',
                   controller = msdrive)

    # start http server
    #

    cherrypy.log ("Mounting root", context = 'ENGINE', severity = logging.INFO)

    app = cherrypy.tree.mount (root = None, config = config_filename)

    app.merge ({'/': {'request.dispatch': d}})
    return app


if __name__ == '__main__':
    main ()
    cherrypy.engine.start ()
    cherrypy.engine.block ()
