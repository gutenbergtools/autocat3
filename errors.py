#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-
import cherrypy
from BaseSearcher import OpenSearch
from Page import Page
import Formatters

class ErrorPage(Page):
    
    def __init__(self, status=500, message='undefined error'):
        self.message = message
        self.status = status

    def index(self):
        return Formatters.formatters['html'].render('error', self)