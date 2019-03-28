#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
Dropbox.py

Copyright 2012-17 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The send-to-dropbox pages.

"""

from __future__ import unicode_literals

import json
import re

from contextlib import closing

import CloudStorage


class DropboxOAuth2Session (CloudStorage.CloudOAuth2Session):
    """ Hold parameters for OAuth2. """

    name_prefix           = 'dropbox'
    oauth2_auth_endpoint  = 'https://www.dropbox.com/oauth2/authorize'
    oauth2_token_endpoint = 'https://api.dropbox.com/oauth2/token'
    oauth2_scope          = None


class Dropbox (CloudStorage.CloudStorage):
    """ Send files to dropbox using OAuth2 authentication. """

    name                  = 'Dropbox'
    session_class         = DropboxOAuth2Session
    user_agent            = 'PG2Dropbox/0.3'
    upload_endpoint       = 'https://content.dropboxapi.com/2/files/upload'

    # Incompatible characters see: https://www.dropbox.com/help/145/en
    # also added ' and ,
    re_filename = re.compile ('[/\\<>:"|?*\',]')

    def upload_file (self, session, response):
        """ Get the file from gutenberg.org and upload it to dropbox.
        :param session: authorized OAuthlib session.
        """

        parameters = {
            'path': '/' + self.fix_filename (session.ebook.get_filename ())
        }
        headers = {
            'Authorization'   : 'Bearer ' + str (session.token),
            'Content-Type'    : 'application/octet-stream',
            'Dropbox-API-Arg' : json.dumps (parameters)
        }
        with closing (session.post (self.upload_endpoint,
                                    data = response.content,
                                    headers = headers)) as r:
            CloudStorage.error_log (r.text)
            r.raise_for_status ()
