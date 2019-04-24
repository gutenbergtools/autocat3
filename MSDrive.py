#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
MSDrive.py

Distributable under the GNU General Public License Version 3 or newer.

The send-to-onedrive pages using the Graph API
https://docs.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0

"""

from __future__ import unicode_literals

from contextlib import closing

import CloudStorage

class MSDriveSession(CloudStorage.CloudOAuth2Session):
    """ Hold parameters for OAuth. """

    #
    # OAuth 2.0 flow see:
    # http://tools.ietf.org/html/rfc6749
    # http://msdn.microsoft.com/en-us/library/live/hh243649
    #

    name_prefix = 'msdrive'
    oauth2_auth_endpoint = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
    oauth2_token_endpoint = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    oauth2_scope = 'Files.ReadWrite'

class MSDrive(CloudStorage.CloudStorage):
    """ Send files to Microsoft OneDrive. """

    name = 'OneDrive'
    session_class = MSDriveSession
    user_agent = 'PG2OneDrive/2019.0'
    #upload_endpoint = 'https://apis.live.net/v5.0/me/skydrive/files/'
    upload_endpoint = 'https://graph.microsoft.com/v1.0/me/drive/items/root:/Documents/Gutenberg/{filename}:/createUploadSession'
    


    def upload_file(self, session, response):
        """ Upload a file to microsoft onedrive. """
        filename = self.fix_filename(session.ebook.get_filename())
        item_data = {
            'name': filename,
            'description': 'A Project Gutenberg Ebook',
            "@microsoft.graph.conflictBehavior": "rename", 
        }
        filesize = int(response.headers['Content-Length'])
        url = self.upload_endpoint.format(filename=filename)
        chunk_size = 327680 # weird onedrive thing related to FAT tables
        upload_data = session.post(url, json={'item': item_data}).json()

        def headers(start, end, filesize):
            return {
                'Content-Length': str(end - start + 1),
                'Content-Range': 'bytes {}-{}/{}'.format(start, end, filesize)
            }

        if 'uploadUrl' in upload_data:
            session_uri = upload_data['uploadUrl']
            start = 0
            end = min(chunk_size - 1, filesize - 1)

            for chunk in response.iter_content(chunk_size):
                r = session.put(
                    session_uri,
                    data=chunk,
                    headers=headers(start, end, filesize),
                )
                start = start + chunk_size
                end = min(end + chunk_size, filesize - 1)
                r.raise_for_status()
        else:
            CloudStorage.log('no uploadUrl in %s' % upload_data)
        session.close()
