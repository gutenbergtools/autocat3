#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-
"""
diagnostics.py

Copyright 2019 by Eric Hellman

Distributable under the GNU General Public License Version 3 or newer.

"""
import json
import resource
import sys
from collections import Mapping, Container
from sys import getsizeof
import threading

import cherrypy
from cherrypy.lib.sessions import RamSession
from Page import Page

def thread_info():
    return [t.name for t in threading.enumerate()]

def deep_getsizeof(o, ids):
    """Find the memory footprint of a Python object

    This is a recursive function that rills down a Python object graph
    like a dictionary holding nested ditionaries with lists of lists
    and tuples and sets.

    The sys.getsizeof function does a shallow size of only. It counts each
    object inside a container as pointer only regardless of how big it
    really is.

    :param o: the object
    :param ids:
    :return:
    https://github.com/the-gigi/deep/blob/master/deeper.py
    """
    d = deep_getsizeof
    if id(o) in ids:
        return 0

    r = getsizeof(o)
    ids.add(id(o))

    if isinstance(o, str):
        return r

    if isinstance(o, Mapping):
        try:
            return r + sum(d(k, ids) + d(v, ids) for k, v in list(o.items()))
        except RuntimeError:
            return 'error'

    if isinstance(o, Container):
        return r + sum(d(x, ids) for x in o)

    return r

class DiagnosticsPage (Page):
    """ Python health. """

    @cherrypy.tools.json_out()
    def index (self, **dummy_kwargs):
        """ return stats. """
        stats = {}
        stats['sessions'] = len(RamSession.cache)
        stats['sessions_storage'] = deep_getsizeof(RamSession.cache, set())
        stats['allocated_blocks'] = sys.getallocatedblocks()
        stats['rusage_self'] = resource.getrusage(resource.RUSAGE_SELF)
        stats['rusage_children'] = resource.getrusage(resource.RUSAGE_CHILDREN)
        stats['thread_info'] = thread_info()
        return stats

