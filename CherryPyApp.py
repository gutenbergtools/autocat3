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

from libgutenberg import GutenbergDatabase
import i18n_tool

# this import causes ConnectionPool.ConnectionPool to become the cherrypy connection pool
import ConnectionPool

import Page
import StartPage
import SuggestionsPage
from SearchPage import BookSearchPage, AuthorSearchPage, SubjectSearchPage, BookshelfSearchPage, \
    AuthorPage, SubjectPage, BookshelfPage, AlsoDownloadedPage
from BibrecPage import BibrecPage
from AdvSearchPage import AdvSearchPage
import CoverPages
import QRCodePage
import diagnostics
import Sitemap
import Formatters
from errors import ErrorPage

import Timer

plugins.Timer = Timer.TimerPlugin
install_dir = os.path.dirname(os.path.abspath(__file__))

CHERRYPY_CONFIG = os.path.join(install_dir, 'CherryPy.conf')
LOCAL_CONFIG = [os.path.expanduser('~/.autocat3'), '/etc/autocat3.conf']

def error_page_404(status, message, traceback, version):
    resp = ErrorPage(status, message).index()
    
    # signal that we needn't save the session
    cherrypy.session.loaded = False
    return resp


class MyRoutesDispatcher(cherrypy.dispatch.RoutesDispatcher):
    """ Dispatcher that tells us the matched route.

    CherryPy makes it hard for us by forgetting the matched route object.
    Here we add a 'route_name' parameter, that will tell us the route's name.

    """

    def connect(self, name, route, controller, **kwargs):
        """ Add a 'route_name' parameter that will tell us the matched route. """
        kwargs['route_name'] = name
        kwargs.setdefault('action', 'index')
        cherrypy.dispatch.RoutesDispatcher.connect(self, name, route, controller, **kwargs)


def main():
    """ Main function. """

    # default config
    cherrypy.config.update({
        'uid': 0,
        'gid': 0,
        'server_name': 'localhost',
        'genshi.template_dir': os.path.join(install_dir, 'templates'),
        'daemonize': False,
        'pidfile': None,
        'host': 'localhost',
        'file_host': 'localhost',
        })

    cherrypy.config.update(CHERRYPY_CONFIG)

    extra_config = ''
    for config_filename in LOCAL_CONFIG:
        try:
            cherrypy.config.update(config_filename)
            extra_config = config_filename
            break
        except IOError:
            pass

    # Rotating Logs
    # CherryPy will already open log files if present in config
    error_file = access_file = ''
    # read the logger file locations from config file.
    if not cherrypy.log.error_file:
        error_file = cherrypy.config.get('logger.error_file', '')
    if not cherrypy.log.access_file:
        access_file = cherrypy.config.get('logger.access_file', '')

    # disable log file handlers
    cherrypy.log.error_file = ""
    cherrypy.log.access_file = ""

    # set up python logging
    max_bytes = getattr(cherrypy.log, "rot_max_bytes", 100 * 1024 * 1024)
    backup_count = getattr(cherrypy.log, "rot_backup_count", 2)

    if error_file:
        h = logging.handlers.RotatingFileHandler(error_file, 'a', max_bytes, backup_count, 'utf-8')
        h.setLevel(logging.INFO)
        h.setFormatter(cherrypy._cplogging.logfmt)
        cherrypy.log.error_log.addHandler(h)

    if access_file:
        h = logging.handlers.RotatingFileHandler(access_file, 'a', max_bytes, backup_count, 'utf-8')
        h.setLevel(logging.INFO)
        h.setFormatter(cherrypy._cplogging.logfmt)
        cherrypy.log.access_log.addHandler(h)



    if not cherrypy.config['daemonize']:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(cherrypy._cplogging.logfmt)
        cherrypy.log.error_log.addHandler(ch)

    # continue app init
    #

    cherrypy.log('*' * 80, context='ENGINE', severity=logging.INFO)
    cherrypy.log("Using config file '%s'." % CHERRYPY_CONFIG,
                  context='ENGINE', severity=logging.INFO)
    if extra_config:
        cherrypy.log('extra_config: %s' % extra_config, context='ENGINE', severity=logging.INFO)

    # after cherrypy.config is parsed
    Formatters.init()
    cherrypy.log("Continuing App Init", context='ENGINE', severity=logging.INFO)

    cherrypy.log("Continuing App Init", context='ENGINE', severity=logging.INFO)
    cherrypy.tools.I18nTool = i18n_tool.I18nTool()

    cherrypy.log("Continuing App Init", context='ENGINE', severity=logging.INFO)


    cherrypy.config['all_hosts'] = (
        cherrypy.config['host'], cherrypy.config['file_host'])
    
    cherrypy.config.update({'error_page.404': error_page_404})

    if hasattr(cherrypy.engine, 'signal_handler'):
        cherrypy.engine.signal_handler.subscribe()

    GutenbergDatabase.options.update(cherrypy.config)
    cherrypy.engine.pool = plugins.ConnectionPool(
        cherrypy.engine, params=GutenbergDatabase.get_connection_params(cherrypy.config))
    cherrypy.engine.pool.subscribe()

    plugins.Timer(cherrypy.engine).subscribe()

    cherrypy.log("Daemonizing", context='ENGINE', severity=logging.INFO)

    if cherrypy.config['daemonize']:
        plugins.Daemonizer(cherrypy.engine).subscribe()

    uid = cherrypy.config['uid']
    gid = cherrypy.config['gid']
    if uid > 0 or gid > 0:
        plugins.DropPrivileges(cherrypy.engine, uid=uid, gid=gid, umask=0o22).subscribe()

    if cherrypy.config['pidfile']:
        pid = plugins.PIDFile(cherrypy.engine, cherrypy.config['pidfile'])
        # Write pidfile after privileges are dropped(prio == 77)
        # or we will not be able to remove it.
        cherrypy.engine.subscribe('start', pid.start, 78)
        cherrypy.engine.subscribe('exit', pid.exit, 78)


    cherrypy.log("Setting up routes", context='ENGINE', severity=logging.INFO)

    # setup 'routes' dispatcher
    #
    # d = cherrypy.dispatch.RoutesDispatcher(full_result=True)
    d = MyRoutesDispatcher(full_result=True)
    cherrypy.routes_mapper = d.mapper

    def check_id(environ, result):
        """ Check if id is a valid number. """
        try:
            return str(int(result['id'])) == result['id']
        except:
            return False

    d.connect('start', r'/ebooks{.format}/',
               controller=StartPage.Start())

    d.connect('suggest', r'/ebooks/suggest{.format}/',
               controller=SuggestionsPage.Suggestions())

    # search pages

    d.connect('search', r'/ebooks/search{.format}/',
               controller=BookSearchPage())

    d.connect('author_search', r'/ebooks/authors/search{.format}/',
               controller=AuthorSearchPage())

    d.connect('subject_search', r'/ebooks/subjects/search{.format}/',
               controller=SubjectSearchPage())

    d.connect('bookshelf_search', r'/ebooks/bookshelves/search{.format}/',
               controller=BookshelfSearchPage())

    d.connect('results', r'/ebooks/results{.format}/',
               controller=AdvSearchPage())

    # 'id' pages

    d.connect('author', r'/ebooks/author/{id:\d+}{.format}',
               controller=AuthorPage(), conditions=dict(function=check_id))

    d.connect('subject', r'/ebooks/subject/{id:\d+}{.format}',
               controller=SubjectPage(), conditions=dict(function=check_id))

    d.connect('bookshelf', r'/ebooks/bookshelf/{id:\d+}{.format}',
               controller=BookshelfPage(), conditions=dict(function=check_id))

    d.connect('also', r'/ebooks/{id:\d+}/also/',
               controller=AlsoDownloadedPage(), conditions=dict(function=check_id))

    # bibrec pages

    d.connect('download', r'/ebooks/{id:\d+}/download{.format}',
               controller=Page.NullPage(), _static=True)

    d.connect('bibrec', r'/ebooks/{id:\d+}{.format}',
               controller=BibrecPage(), conditions=dict(function=check_id))


    # legacy compatibility with /ebooks/123.bibrec
    d.connect('bibrec2', r'/ebooks/{id:\d+}.bibrec{.format}',
               controller=BibrecPage(), conditions=dict(function=check_id))

    d.connect('cover', r'/covers/{size:small|medium}/{order:latest|popular|random}/{count}',
               controller=CoverPages.CoverPages())

    d.connect('qrcode', r'/qrcode/',
               controller=QRCodePage.QRCodePage())

    d.connect('iplimit', r'/iplimit/',
               controller=Page.NullPage())

    d.connect('diagnostics', r'/diagnostics/',
               controller=diagnostics.DiagnosticsPage())

    d.connect('stats', r'/stats/',
               controller=Page.NullPage(), _static=True)

    # /w/captcha/question/ so varnish will cache it
    d.connect('captcha.question', r'/w/captcha/question/',
               controller=Page.GoHomePage())

    d.connect('captcha.answer', r'/w/captcha/answer/',
               controller=Page.GoHomePage())

    # sitemap protocol access control requires us to place sitemaps in /ebooks/
    d.connect('sitemap', r'/ebooks/sitemaps/',
               controller=Sitemap.SitemapIndex())

    d.connect('sitemap_index', r'/ebooks/sitemaps/{page:\d+}',
               controller=Sitemap.Sitemap())

    if 'dropbox_client_id' in cherrypy.config:
        import Dropbox
        dropbox = Dropbox.Dropbox()
        cherrypy.log("Dropbox Client Id: %s" % cherrypy.config['dropbox_client_id'],
                      context='ENGINE', severity=logging.INFO)
        d.connect('dropbox_send', r'/ebooks/send/dropbox/{id:\d+}.{filetype}',
                   controller=dropbox, conditions=dict(function=check_id))
        d.connect('dropbox_callback', r'/ebooks/send/dropbox/',
                   controller=dropbox)

    if 'gdrive_client_id' in cherrypy.config:
        import GDrive
        gdrive = GDrive.GDrive()
        cherrypy.log("GDrive Client Id: %s" % cherrypy.config['gdrive_client_id'],
                      context='ENGINE', severity=logging.INFO)
        d.connect('gdrive_send', r'/ebooks/send/gdrive/{id:\d+}.{filetype}',
                   controller=gdrive, conditions=dict(function=check_id))
        d.connect('gdrive_callback', r'/ebooks/send/gdrive/',
                   controller=gdrive)

    if 'msdrive_client_id' in cherrypy.config:
        import MSDrive
        msdrive = MSDrive.MSDrive()
        cherrypy.log("MSDrive Client Id: %s" % cherrypy.config['msdrive_client_id'],
                      context='ENGINE', severity=logging.INFO)
        d.connect('msdrive_send', r'/ebooks/send/msdrive/{id:\d+}.{filetype}',
                   controller=msdrive, conditions=dict(function=check_id))
        d.connect('msdrive_callback', r'/ebooks/send/msdrive/',
                   controller=msdrive)

    # start http server
    #

    cherrypy.log("Mounting root", context='ENGINE', severity=logging.INFO)

    app = cherrypy.tree.mount(root=None, config=CHERRYPY_CONFIG)

    app.merge({'/': {'request.dispatch': d}})
    return app


if __name__ == '__main__':
    main()
    cherrypy.engine.start()
    cherrypy.engine.block()
