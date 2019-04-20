#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
MSDrive.py

Copyright 2014,15 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

The send-to-microsoft-drive pages.

"""

from __future__ import unicode_literals

from contextlib import closing

import CloudStorage


class MSDriveSession (CloudStorage.CloudOAuth2Session):
    """ Hold parameters for OAuth. """

    #
    # OAuth 2.0 flow see:
    # http://tools.ietf.org/html/rfc6749
    # http://msdn.microsoft.com/en-us/library/live/hh243649
    #

    name_prefix           = 'msdrive'
    oauth2_auth_endpoint  = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
    oauth2_token_endpoint = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    oauth2_scope          = 'files.readwrite'

class MSDrive (CloudStorage.CloudStorage):
    """ Send files to Microsoft Drive. """

    name                  = 'OneDrive'
    session_class         = MSDriveSession
    user_agent            = 'PG2OneDrive/2019.0'
    #upload_endpoint       = 'https://apis.live.net/v5.0/me/skydrive/files/'
    upload_endpoint       = 'https://graph.microsoft.com/v1.0/me/drive/items/root:/{filename}:/createUploadSession'


    def upload_file (self, session, request):
        """ Upload a file to microsoft drive. """

        url = self.upload_endpoint.format(
            {'filename': self.fix_filename (session.ebook.get_filename ())}
        )

        upload_session = session.post (url)
        if 'uploadUrl' in upload_session:
            with closing (session.put (upload_session['uploadUrl'], data = request.iter_content (1024 * 1024))) as r:
                r.raise_for_status ()
