#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-
"""
MetricsPage.py

Copyright 2026 by Casey Peel

Distributable under the GNU General Public License Version 3 or newer.

"""
import resource
import threading

import cherrypy
from Page import Page

class MetricsPage (Page):
    """ prometheus-exporter style metrics """

    def index (self, **dummy_kwargs):
        """ return metrics. """

        core_metrics = {
            "autocat3_total_threads": threading.active_count(),
            "autocat3_memory_kb_self": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "autocat3_memory_kb_children": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        }

        http_server = cherrypy.server
        http_server_metrics = {
            "autocat3_httpserver_socket_queue_size": http_server.socket_queue_size,
            "autocat3_httpserver_accepted_queue_size": http_server.accepted_queue_size,
            "autocat3_httpserver_pool_minsize": http_server.thread_pool,
            # we include thread_pool_max even though the value is currently completely
            # meaningless https://github.com/cherrypy/cheroot/issues/190
            "autocat3_httpserver_pool_maxsize": http_server.thread_pool_max,
        }

        # https://docs.cherrypy.dev/en/latest/_modules/cherrypy/_cpserver.html#Server
        # This assumes we're using the default CherryPy cheroot HTTP server
        if (hasattr(cherrypy.server.httpserver, "requests")):
            http_server_pool = cherrypy.server.httpserver.requests
            http_server_metrics = http_server_metrics | {
                "autocat3_httpserver_pool_available": http_server_pool.idle,
                "autocat3_httpserver_pool_size": len(http_server_pool._threads),
                "autocat3_httpserver_pool_used": len(http_server_pool._threads) - http_server_pool.idle,
                "autocat3_httpserver_pool_queued": http_server_pool.qsize,
            }

        # https://github.com/sqlalchemy/sqlalchemy/blob/d5c89a541f5233baf6b6a7498746820caa7b407f/lib/sqlalchemy/pool/impl.py
        if cherrypy.engine.pool.engine:
            db_pool = cherrypy.engine.pool.pool
            db_metrics = {
                "autocat3_sqlalchemy_pool_maxsize": db_pool.size(),
                "autocat3_sqlalchemy_pool_available": db_pool.checkedin(),
                "autocat3_sqlalchemy_pool_used": db_pool.checkedout(),
                "autocat3_sqlalchemy_pool_overflow": db_pool.overflow(),
            }
        else:
            db_metrics = {}

        metrics = core_metrics | http_server_metrics | db_metrics

        cherrypy.response.headers['Content-Type'] = 'text/plain'

        return "\n".join([f"{metric} {value}" for metric, value in metrics.items()]) + "\n"
