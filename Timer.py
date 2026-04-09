#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
Timer.py

Copyright 2010-2013 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

A cron-like process that runs at fixed intervals.

Usage:
  import Timer
  cherrypy.process.plugins.Timer = TimerPlugin

"""

from __future__ import unicode_literals

import datetime
import logging

import psycopg2
import cherrypy

from libgutenberg import GutenbergDatabase

import BaseSearcher


class TimerPlugin (cherrypy.process.plugins.Monitor):
    """ Plugin to start the timer thread.

    We cannot start any threads before daemonizing,
    so we must start the timer thread by this plugin.

    """

    def __init__ (self, bus):
        frequency = 300
        super (TimerPlugin, self).__init__ (bus, self.tick, frequency)
        self.name = 'timer'
        self._last_refresh_date = None

    def start (self):
        super (TimerPlugin, self).start ()
        self.tick (startup=True)
    start.priority = 80

    def tick (self, startup=False):
        """ Do things here. """

        try:
            BaseSearcher.books_in_archive = BaseSearcher.sql_get ('select count (*) from books')
        except:
            pass

        refresh_hour = cherrypy.config.get ('mv_refresh_hour', 17)
        now = datetime.datetime.now ()

        if startup or (now.hour == refresh_hour and self._last_refresh_date != now.date ()):
            self._try_refresh_mv ()

    def _try_refresh_mv (self):
        """ Refresh mv_books_dc, skipping if another instance is already refreshing.

        — Zachary Rosario

        Bypasses the pool to avoid statement timeout errors.
        pguser needs EXECUTE on refresh_mv_books_dc() and ownership of mv_books_dc.
        """
        conn = None
        try:
            params = GutenbergDatabase.get_connection_params (cherrypy.config)
            conn = psycopg2.connect (**params)
            cur = conn.cursor ()

            # Transaction-level advisory lock keyed on the view's OID.
            # Auto-releases on commit/rollback — no explicit unlock needed.
            cur.execute ("""
                SELECT pg_try_advisory_xact_lock(c.oid::bigint)
                FROM pg_class c WHERE c.relname = 'mv_books_dc'
            """)
            if not cur.fetchone ()[0]:
                return

            cur.execute ("SELECT refresh_mv_books_dc()")
            conn.commit ()
            self._last_refresh_date = datetime.date.today ()
            cherrypy.log ("MV refresh completed.", context='TIMER', severity=logging.INFO)
        except Exception as e:
            cherrypy.log ("MV refresh failed: %s" % e, context='TIMER', severity=logging.ERROR)
        finally:
            if conn:
                conn.close ()
