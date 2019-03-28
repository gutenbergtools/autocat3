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

import cherrypy

import BaseSearcher


class TimerPlugin (cherrypy.process.plugins.Monitor):
    """ Plugin to start the timer thread.

    We cannot start any threads before daemonizing,
    so we must start the timer thread by this plugin.

    """

    def __init__ (self, bus):
        # interval in seconds
        frequency = 300
        super (TimerPlugin, self).__init__ (bus, self.tick, frequency)
        self.name = 'timer'

    def start (self):
        super (TimerPlugin, self).start ()
        self.tick ()
    start.priority = 80

    def tick (self):
        """ Do things here. """

        try:
            BaseSearcher.books_in_archive = BaseSearcher.sql_get ('select count (*) from books')
        except:
            pass
