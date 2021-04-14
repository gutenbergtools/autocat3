#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
ConnectionPool.py

Copyright 2010 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

"""

from __future__ import unicode_literals

import logging

import psycopg2

import sqlalchemy.pool as pool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cherrypy
from cherrypy.process import plugins

DUMMY_SQL_URL = "postgresql://127.0.0.1:5432/gutenberg"

class ConnectionCreator():
    """ Creates connections for the connection pool. """

    def __init__(self, params):
        self.params = params

    def __call__(self):
        cherrypy.log(
            "Connecting to database '%(database)s' on '%(host)s:%(port)d' as user '%(user)s'."
            % self.params, context='POSTGRES', severity=logging.INFO)
        conn = psycopg2.connect(**self.params)
        conn.cursor().execute('SET statement_timeout = 5000')
        return conn


class ConnectionPool(plugins.SimplePlugin):
    """A WSPBus plugin that controls a SQLAlchemy engine/connection pool."""

    def __init__(self, bus, params=None):
        plugins.SimplePlugin.__init__(self, bus)
        self.params = params
        self.name = 'sqlalchemy'
        self.pool = None


    def _start(self):
        """ Init the connection pool. """

        pool_size = cherrypy.config.get('sqlalchemy.pool_size', 5)
        max_overflow = cherrypy.config.get('sqlalchemy.max_overflow', 10)
        timeout = cherrypy.config.get('sqlalchemy.timeout', 30)
        recycle = cherrypy.config.get('sqlalchemy.recycle', 3600)

        self.bus.log("... pool_size = %d, max_overflow = %d" % (pool_size, max_overflow))
        my_pool = pool.QueuePool(ConnectionCreator(self.params),
                                 pool_size=pool_size,
                                 max_overflow=max_overflow,
                                 timeout=timeout,
                                 recycle=recycle)
        engine = create_engine(DUMMY_SQL_URL, echo=False, pool=my_pool)
        Session = sessionmaker(bind=engine)
        return my_pool, Session

    def connect(self):
        """ Return a connection. """

        return self.pool.connect()


    def start(self):
        """ Called on engine start. """

        if self.pool is None:
            self.bus.log("Creating the SQL connectors ...")
            self.pool, self.Session = self._start()
        else:
            self.bus.log("SQL connectors already exists.")


    def stop(self):
        """ Called on engine stop. """

        if self.pool is not None:
            self.bus.log("Disposing the SQL connection pool.")
            self.Session = None
            self.pool.dispose()
            self.pool = None


    def graceful(self):
        """ Called on engine restart. """

        if self.pool is not None:
            self.bus.log("Restarting the SQL connection pool ...")
            self.pool.dispose()
            self.pool = self._start()


cherrypy.process.plugins.ConnectionPool = ConnectionPool
