#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
GDrive.py

Copyright 2013-15 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The send-to-google-drive pages.

"""

from __future__ import unicode_literals

from contextlib import closing
import json

import CloudStorage


class GDriveSession (CloudStorage.CloudOAuth2Session):
    """ Hold parameters for OAuth. """

    #
    # OAuth 2.0 flow see:
    # http://tools.ietf.org/html/rfc6749
    # https://developers.google.com/api-client-library/python/guide/aaa_oauth
    #

    name_prefix           = 'gdrive'
    oauth2_auth_endpoint  = 'https://accounts.google.com/o/oauth2/auth'
    oauth2_token_endpoint = 'https://accounts.google.com/o/oauth2/token'
    # Check https://developers.google.com/drive/web/scopes for all available scopes
    oauth2_scope          = 'https://www.googleapis.com/auth/drive.file'


class GDrive (CloudStorage.CloudStorage):
    """ Send files to Google Drive. """

    name                  = 'Google Drive'
    session_class         = GDriveSession
    user_agent            = 'PG2GDrive/0.2'
    upload_endpoint       = 'https://www.googleapis.com/upload/drive/v2/files?uploadType=resumable'


    def upload_file (self, session, request):
        """ Upload a file to google drive. """

        file_metadata = {
            'title': self.fix_filename (session.ebook.get_filename ()),
            'description': 'A Project Gutenberg Ebook',
        }
        headers = {
            'X-Upload-Content-Type': request.headers['Content-Type'],
            'X-Upload-Content-Length': request.headers['Content-Length'],
            'Content-Type': 'application/json; charset=UTF-8',
        }
        with closing (session.post (self.upload_endpoint,
                                    data = json.dumps (file_metadata),
                                    headers = headers)) as r2:
            r2.raise_for_status ()
            session_uri = r2.headers['Location']

        headers = {
            'Content-Type': request.headers['Content-Type'],
        }
        with closing (session.put (session_uri,
                                   data = request.iter_content (1024 * 1024),
                                   headers = headers)) as r3:
            r3.raise_for_status ()
