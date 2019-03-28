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
    oauth2_auth_endpoint  = 'https://login.live.com/oauth20_authorize.srf'
    oauth2_token_endpoint = 'https://login.live.com/oauth20_token.srf'
    oauth2_scope          = 'wl.signin wl.basic wl.skydrive wl.skydrive_update'


class MSDrive (CloudStorage.CloudStorage):
    """ Send files to Microsoft Drive. """

    name                  = 'OneDrive'
    session_class         = MSDriveSession
    user_agent            = 'PG2MSDrive/0.2'
    upload_endpoint       = 'https://apis.live.net/v5.0/me/skydrive/files/'


    def upload_file (self, session, request):
        """ Upload a file to microsoft drive. """

        url = self.upload_endpoint + self.fix_filename (session.ebook.get_filename ())

        # MSDrive does not like such never-heard-of-before
        # content-types like 'epub', so we just send it without
        # content-type.
        with closing (session.put (url, data = request.iter_content (1024 * 1024))) as r:
            r.raise_for_status ()
