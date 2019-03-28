#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
PostgresSession.py

Copyright 2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

A rewrite of the cherrypy PostgresqlSession.

Usage:
  import PostgresSession
  cherrypy.lib.sessions.PostgresSession = PostgresSession.PostgresSession

"""

import datetime
import logging
import pickle

import cherrypy
import cherrypy.lib.sessions


class PostgresSession (cherrypy.lib.sessions.Session):
    """ Implementation of the PostgreSQL backend for sessions. It assumes
    a table like this::

      create table <table_name> (
        id       varchar (40)  primary key,
        expires  timestamp,
        data     bytea
      )

    You must provide your own `get_dbapi20_connection ()` function.
    """

    pickle_protocol = pickle.HIGHEST_PROTOCOL
    select = 'select expires, data from table_name where id=%(id)s for update'


    def __init__ (self, id_ = None, **kwargs):
        self.table_name = kwargs.get ('table', 'session')
        # Session.__init__ () may need working connection
        self.connection = self.get_dbapi20_connection ()

        super (PostgresSession, self).__init__ (id_, **kwargs)


    @staticmethod
    def get_dbapi20_connection ():
        """ Return a dbapi 2.0 compatible connection. """
        return cherrypy.engine.pool.connect ()


    @classmethod
    def setup (cls, **kwargs):
        """Set up the storage system for Postgres-based sessions.

        This should only be called once per process; this will be done
        automatically when using sessions.init (as the built-in Tool does).
        """

        cherrypy.log ("Using PostgresSession",
                      context = 'SESSION', severity = logging.INFO)

        for k, v in kwargs.items ():
            setattr (cls, k, v)


    def now (self):
        """Generate the session specific concept of 'now'.

        Other session providers can override this to use alternative,
        possibly timezone aware, versions of 'now'.
        """
        return datetime.datetime.utcnow ()


    def _exec (self, sql, **kwargs):
        """ Internal helper to execute sql statements. """

        kwargs['id'] = self.id
        cursor = self.connection.cursor ()
        cursor.execute (sql.replace ('table_name', self.table_name), kwargs)
        return cursor


    def _exists (self):
        """ Return true if session data exists. """
        cursor = self._exec (self.select)
        return bool (cursor.fetchall ())


    def _load (self):
        """ Load the session data. """

        cursor = self._exec (self.select)
        rows = cursor.fetchall ()
        if not rows:
            return None

        expires, pickled_data = rows[0]
        data = pickle.loads (pickled_data)
        return data, expires


    def _save (self, expires):
        """ Save the session data. """

        pickled_data = pickle.dumps (self._data, self.pickle_protocol)

        self._delete ()
        self._exec (
            """\
            insert into table_name (id, expires, data)
                values (%(id)s, %(expires)s, %(data)s)
            """,
            data = pickled_data,
            expires = expires
        )


    def _delete (self):
        """ Delete the session data. """
        self._exec ('delete from table_name where id=%(id)s')


    def acquire_lock (self):
        """Acquire an exclusive lock on the currently-loaded session data."""

        self._exec (self.select)
        self.locked = True


    def release_lock (self):
        """Release the lock on the currently-loaded session data."""

        self.connection.commit ()
        self.locked = False


    def clean_up (self):
        """Clean up expired sessions."""

        self._exec (
            'delete from table_name where expires < %(now)s',
            now = self.now ()
        )
