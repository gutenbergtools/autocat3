#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
MyRamSession.py

Copyright 2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

A quick Python3 fix for the cherrypy RamSession. May be removed when
RamSession is fixed upstream.

Usage:
  import MyRamSession
  cherrypy.lib.sessions.RamSession   = MyRamSession.FixedRamSession
  cherrypy.lib.sessions.MyramSession = MyRamSession.MyRamSession

"""

import threading

import cherrypy
import cherrypy.lib.sessions


class Struct (object):
    """ Data store. """

    def __init__ (self):
        self.expires = None
        self.data = None
        self.cache_lock = threading.Lock ()


class MyRamSession (cherrypy.lib.sessions.Session):
    """ A cherrypy session kept in ram. """

    cache = {}
    # all inserts/deletes in cache must be guarded by this lock
    # or we will get 'RuntimeError: dictionary changed size during iteration'
    # because you cannot atomically iterate a dict in Python3
    cache_lock = threading.Lock ()


    def __init__ (self, id_ = None, **kwargs):
        super (MyRamSession, self).__init__ (id_, **kwargs)


    def clean_up (self):
        """Clean up expired sessions."""

        now = self.now ()
        def expired (x):
            return x[1].expires <= now

        with self.cache_lock:
            for id_, s in list (filter (expired, self.cache.items ())):
                self.cache.pop (id_, None)


    def _exists (self):
        return self.id in self.cache


    def _load (self):
        try:
            s = self.cache[self.id]
            return s.data, s.expires
        except KeyError:
            return None


    def _save (self, expires):
        s = self.cache.get (self.id, Struct ())
        s.expires = expires
        s.data = self._data
        with self.cache_lock:
            self.cache[self.id] = s


    def _delete (self):
        with self.cache_lock:
            self.cache.pop (self.id, None)


    def acquire_lock (self):
        """Acquire an exclusive lock on the currently-loaded session data."""

        try:
            self.cache[self.id].lock.acquire ()
            self.locked = True
        except KeyError:
            pass


    def release_lock (self):
        """Release the lock on the currently-loaded session data."""

        try:
            self.cache[self.id].lock.release ()
            self.locked = False
        except KeyError:
            pass


    def __len__ (self):
        """Return the number of active sessions."""

        return len (self.cache)


from cherrypy._cpcompat import copyitems

class FixedRamSession (cherrypy.lib.sessions.RamSession):

    def clean_up(self):
        """Clean up expired sessions."""
        now = self.now()

        try:
            for id, (data, expiration_time) in copyitems(self.cache):
                if expiration_time <= now:
                    try:
                        del self.cache[id]
                    except KeyError:
                        pass
                    try:
                        del self.locks[id]
                    except KeyError:
                        pass

            # added to remove obsolete lock objects
            for id in list(self.locks):
                if id not in self.cache:
                    self.locks.pop(id, None)

        except RuntimeError:
            # RuntimeError: dictionary changed size during iteration
            # Do nothig. Keep cleanup thread running and maybe next time lucky.
            pass
