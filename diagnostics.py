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
from Page import Page
from cherrypy.lib.sessions import RamSession

class DiagnosticsPage (Page):
    """ Python health. """
    
    def index (self, **dummy_kwargs):
        """ return stats. """
        stats = {}
        stats['sessions'] = len(RamSession.cache)
        stats['allocated_blocks'] = sys.getallocatedblocks()
        stats['rusage_self'] = resource.rusage(resource.RUSAGE_SELF)
        stats['rusage_children'] = resource.rusage(resource.RUSAGE_CHILDREN)
        return json.dumps(stats)
