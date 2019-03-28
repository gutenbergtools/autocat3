#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
StatsPage.py

Copyright 2009-2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The appserver stats page.

"""

from __future__ import unicode_literals

import cherrypy

import BaseSearcher
import TemplatedPage
import asyncdns
import ipinfo


class StatsPage (TemplatedPage.TemplatedPage):
    """ Output some statistics. """

    CONTENT_TYPE = 'application/xhtml+xml; charset=UTF-8'
    FORMATTER = 'html'

    def index (self, **kwargs):
        """ Output stats. """

        backends = int (BaseSearcher.sql_get ("SELECT count (*) from pg_stat_activity"))
        active_backends = int (BaseSearcher.sql_get (
            "SELECT count (*) - 1 from pg_stat_activity where current_query !~ '^<IDLE>'"))

        ipsessions = list (cherrypy.tools.rate_limiter.cache.values ()) # pylint: disable=E1101

        adns = asyncdns.AsyncDNS ()

        # blocked IPs
        blocked = sorted ([s for s in ipsessions if s.get ('blocked', 0) >= 2],
                          key = lambda s: s.ips.sort_key ())
        if 'resolve' in kwargs:
            for d in blocked:
                if d.ips.ipinfo is None:
                    d.ips.ipinfo = ipinfo.IPInfo (adns, d.ips.get_ip_to_block ())

        # active IPs
        active = sorted ([s for s in ipsessions if s.get ('active', False)],
                         key = lambda s: s.ips.sort_key ())

        # busiest IPs
        busiest = sorted ([s for s in active if s.get ('blocked', 0) < 2],
                          key = lambda x: -x.get ('rhits'))[:10]
        if 'resolve' in kwargs:
            for d in busiest:
                if d.ips.ipinfo is None:
                    d.ips.ipinfo = ipinfo.IPInfo (adns, d.ips.get_ip_to_block ())

        # IPs with most sessions
        most_sessions = sorted ([s for s in active
                                 if not s.ips.whitelisted and len (s.sessions) > 1],
                                key = lambda s: -len (s.sessions))[:10]
        if 'resolve' in kwargs:
            for d in most_sessions:
                if d.ips.ipinfo is None:
                    d.ips.ipinfo = ipinfo.IPInfo (adns, d.ips.get_ip_to_block ())

        adns.wait ()
        adns.cancel ()

        return self.output ('stats',
                            active = active,
                            blocked = blocked,
                            busiest = busiest,
                            most_sessions = most_sessions,
                            resolve = 'resolve' in kwargs,
                            rl = cherrypy.tools.rate_limiter, # pylint: disable=E1101
                            backends = backends,
                            active_backends = active_backends)
