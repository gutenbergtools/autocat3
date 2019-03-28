#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CaptchaPage.py

Copyright 2013-14 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Serve a captcha page.

"""

from __future__ import unicode_literals

import requests
import cherrypy
import logging

import Page
import BaseSearcher

#
# reCaptcha API docs:
# https://developers.google.com/recaptcha/docs/verify
#

API = "http://www.google.com/recaptcha/api/verify"


class QuestionPage (Page.Page):
    """ Output captcha page. """

    def index (self, **kwargs):
        """ Output captcha. """

        cherrypy.lib.caching.expires (3600, True)

        os = BaseSearcher.OpenSearch ()
        os.template = 'recaptcha'
        os.recaptcha_public_key = cherrypy.config['recaptcha_public_key']
        os.error = kwargs.get ('error')
        os.finalize ()

        # Remove Session cookie, so that page can be cached.
        name = cherrypy.serving.request.config.get ('tools.sessions.name', 'session_id')
        del cherrypy.serving.response.cookie[name]

        return self.format (os)


class AnswerPage (object):
    """ Check answer with google. """

    def index (self, **kwargs):
        """ Check with google. """

        cherrypy.lib.caching.expires (0, True)

        os = BaseSearcher.OpenSearch ()

        # Remove Session cookie.
        name = cherrypy.serving.request.config.get ('tools.sessions.name', 'session_id')
        del cherrypy.serving.response.cookie[name]

        if 'recaptcha_challenge_field' in kwargs:
            response = submit (
                kwargs['recaptcha_challenge_field'],
                kwargs['recaptcha_response_field'],
                cherrypy.config['recaptcha_private_key'],
                cherrypy.request.remote.ip)

            cherrypy.ipsession.captcha_answer (response)

            if not response.is_valid:
                raise cherrypy.HTTPRedirect (
                    os.url ('captcha.question', error = 'incorrect-captcha-sol'))

        for req in reversed (cherrypy.ipsession['requests']):
            if 'captcha' not in req:
                raise cherrypy.HTTPRedirect (req)

        raise cherrypy.HTTPRedirect (os.url ('start'))

#
# Following is stolen from pypi package recaptcha-client 1.0.6
#   http://code.google.com/p/recaptcha/
# to make it compatible with Python 3 requests.
#

class RecaptchaResponse (object):
    """ The response from the reCaptcha server. """

    def __init__ (self, is_valid, error_code = None):
        self.is_valid = is_valid
        self.error_code = error_code


def submit (recaptcha_challenge_field,
            recaptcha_response_field,
            private_key,
            remoteip):
    """
    Submits a reCAPTCHA request for verification. Returns RecaptchaResponse
    for the request

    recaptcha_challenge_field -- The value of recaptcha_challenge_field from the form
    recaptcha_response_field -- The value of recaptcha_response_field from the form
    private_key -- your reCAPTCHA private key
    remoteip -- the user's ip address
    """

    if not (recaptcha_response_field and recaptcha_challenge_field and
            len (recaptcha_response_field) and len (recaptcha_challenge_field)):
        return RecaptchaResponse (is_valid = False, error_code = 'incorrect-captcha-sol')


    data = {
        'privatekey': private_key,
        'remoteip':   remoteip,
        'challenge':  recaptcha_challenge_field,
        'response':   recaptcha_response_field,
    }
    headers = {
        "User-agent": "reCAPTCHA Python"
    }

    cherrypy.log ('Data=' + repr (data), context = 'CAPTCHA', severity = logging.INFO)

    try:
        r = requests.post (API, data = data, headers = headers)
        r.raise_for_status ()

        lines = r.text.splitlines ()

        cherrypy.log ('Response=' + "/".join (lines), context = 'CAPTCHA', severity = logging.INFO)

        if lines[0] == "true":
            return RecaptchaResponse (is_valid = True)
        else:
            return RecaptchaResponse (is_valid = False, error_code = lines[1])

    except requests.exceptions.RequestException as what:
        cherrypy.log (str (what), context = 'CAPTCHA', severity = logging.ERROR)
        return RecaptchaResponse (is_valid = False, error_code = 'recaptcha-not-reachable')
