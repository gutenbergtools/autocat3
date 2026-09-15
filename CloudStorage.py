#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
CloudStorage.py

Copyright 2013-15 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Base classes for uploads to file hosting services.

"""

from __future__ import unicode_literals

from contextlib import closing
from six.moves import urllib
import logging
import re
import os

import cherrypy
import routes
import requests
import requests_oauthlib

from requests import RequestException
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from i18n_tool import ugettext as _
import BaseSearcher

# pylint: disable=R0921

# Google Drive `bug´ see:
# https://github.com/idan/oauthlib/commit/ca4811b3087f9d34754d3debf839e247593b8a39
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

config = cherrypy.config

urlgen = routes.URLGenerator (cherrypy.routes_mapper, {
    'HTTP_HOST': config['host'],
    'HTTPS': config['host_https']
})

def log (msg):
    """ Log an informational  message. """
    cherrypy.log (msg, context = 'CLOUDSTORAGE', severity = logging.INFO)


def error_log (msg):
    """ Log an error message. """
    cherrypy.log ('Error: ' + msg, context = 'CLOUDSTORAGE', severity = logging.ERROR)


class CloudOAuth2Session (requests_oauthlib.OAuth2Session): # pylint: disable=R0904
    """ An OAuth2 session. """

    name_prefix           = None
    oauth2_auth_endpoint  = None
    oauth2_token_endpoint = None
    oauth2_scope          = None


    def __init__ (self, **kwargs):
        """ Initialize session from cherrypy config. """

        prefix = self.name_prefix

        client_id     = config[prefix + '_client_id']
        redirect_uri  = urlgen (prefix + '_callback', host = config['host'])

        super (CloudOAuth2Session, self).__init__ (
            client_id = client_id,
            scope = self.oauth2_scope,
            redirect_uri = redirect_uri,
            **kwargs
        )

        self.client_secret = config[prefix + '_client_secret']


    def oauth_dance (self, code=None):
        """ Do the OAuth2 dance. """

        #
        # OAuth 2.0 flow see:
        # http://tools.ietf.org/html/rfc6749
        #

        if not self.token:
            if not code:
                # oauth step 1:
                # redirect the user to the Authorization Endpoint
                log ('Building auth url ...')
                auth_url, dummy_state = self.authorization_url (
                    self.oauth2_auth_endpoint)
                log ('Redirecting user to auth endpoint ...')
                raise cherrypy.HTTPRedirect (auth_url)

            else:
                # oauth step 2
                # the user's browser just came back with an authorization code
                # get the access_token from the Token Endpoint
                log ('Fetching access token ...')
                self.fetch_token (self.oauth2_token_endpoint,
                                  client_secret = self.client_secret,
                                  code = code)
                log ('Got access token.')


    def unauthorized (self, msg = 'Unauthorized'):
        """ Called on OAuth2 failure. """
        pass



class CloudStorage (object):
    """ Base class for uploads to cloud storage providers.

    :param name: The name of the cloud service, eg. 'Dropbox'.
    :param session_class: The class to use for the oauth session.
    :param user_agent: The user agent to make requests to www.gutenberg.org.

    """

    name            = None
    session_class   = CloudOAuth2Session
    user_agent      = None
    upload_endpoint = None
    re_filename     = re.compile (r'[/\<>:"|?* ]')


    def __init__ (self):
        self.host = cherrypy.config['host']
        self.urlgen = urlgen
        self.ebook = None

    # Enable sessions for this page and force no-caching by proxies
    @cherrypy.config(**{'tools.sessions.on': True, 'tools.expires.secs': 0, 'tools.expires.force': True})
    def index (self, **kwargs):
        """ Output the page. """

        #
        # OAuth 2.0 flow see:
        # http://tools.ietf.org/html/rfc6749
        #

        if 'id' in kwargs:
            # Load the desired ebook from the URL and set the cookie for
            # the return from the OAuth dance
            self.ebook = EbookMetaData(kwargs["id"], kwargs["filetype"])
            cherrypy.response.cookie[self.cookie_ebook_id] = kwargs["id"]
            cherrypy.response.cookie[self.cookie_ebook_filetype] = kwargs["filetype"]
        elif self.cookie_ebook_id in cherrypy.request.cookie:
            # Load the ebook from the user's cookies on the return from
            # the OAuth dance
            self.ebook = EbookMetaData(
                cherrypy.request.cookie[self.cookie_ebook_id].value,
                cherrypy.request.cookie[self.cookie_ebook_filetype].value
            )
        if self.ebook is None:
            raise cherrypy.HTTPError (400, "No eBook selected. Are your cookies enabled?")

        name = self.name

        if 'not_approved' in kwargs or 'error' in kwargs:
            self._dialog (
                _('Sorry. The file could not be sent to {name}.').format (name = name),
                _('Error'))
            self.redirect_done ()

        # Create the OAuth session (this is not the cherrypy session)
        session = self.session_class()
        try:
            session.oauth_dance (kwargs.get("code"))
            log ("Sending file %s to %s" % (
                self.ebook.get_source_url (), name))

            with closing (self.request_ebook ()) as r:
                r.raise_for_status ()
                self.upload_file (session, r)

            log ("File %s sent to %s" % (
                self.ebook.get_source_url (), name))
            self._dialog (
                _('The file has been sent to {name}.').format (name = name),
                _('Sent to {name}').format (name = name))
            self.redirect_done ()

        except (OAuth2Error, ) as what:
            session.unauthorized (what)
            self.unauthorized ('OAuthError: ' + str (what.urlencoded))

        except (RequestException, IOError, ValueError) as what:
            session.unauthorized (what)
            self.unauthorized ('RequestError: ' + str (what))
            raise cherrypy.HTTPError (500, str (what))


    def upload_file (self, session, response):
        """ Upload the file. """

        raise NotImplementedError

    @property
    def cookie_ebook_id(self):
        return self.session_class.name_prefix + '_ebook_id'

    @property
    def cookie_ebook_filetype(self):
        return self.session_class.name_prefix + '_ebook_filetype'

    def delete_cookies(self):
        # Delete the user cookies that stored the ebook details
        cherrypy.response.cookie[self.cookie_ebook_id] = 0
        cherrypy.response.cookie[self.cookie_ebook_id]["expires"] = 0
        cherrypy.response.cookie[self.cookie_ebook_filetype] = ""
        cherrypy.response.cookie[self.cookie_ebook_filetype]["expires"] = 0

    def request_ebook (self):
        """ Return an open request object for the ebook file. """

        url = self.ebook.get_source_url ()
        # Caveat: use requests.get, not session.get, because it is an insecure
        # transport. session.get would raise InsecureTransportError
        # turn off server encoding since we're going to re-stream the bytes
        return requests.get (
            url,
            headers = {'user-agent': self.user_agent, 'accept-encoding': ''},
            stream = True
        )


    def fix_filename (self, filename):
        """ Replace characters unsupported by many OSs.  """
        return self.re_filename.sub ('_', filename)


    def redirect_done (self):
        """ Redirect user back to bibrec page. """
        self.delete_cookies()

        raise cherrypy.HTTPRedirect (self.urlgen (
            'bibrec', id = self.ebook.id, host = self.host))


    def unauthorized (self, msg = 'Unauthorized'):
        """ Call on OAuth failure. """
        self.delete_cookies()

        msg = str (msg) # msg may be exception class
        error_log (msg)
        raise cherrypy.HTTPError (401, msg)


    @staticmethod
    def _dialog (message, title):
        """ Open a user-visible dialog on the next page. """
        # Set the user response message in the cherrypy session
        cherrypy.session.acquire_lock()
        cherrypy.session['user_dialog'] = (message, title)


class EbookMetaData (object):
    """ Helper class that holds ebook metadata. """

    accepted_filetypes = (
        'epub.images',
        'epub.noimages',
        'epub3.images',
        'kindle.images',
        'kindle.noimages',
        'kf8.images',
        'pdf.images',
        'pdf.noimages',
        'pdf')


    def __init__ (self, id, filetype):
        self.id = None
        self.filetype = None

        try :
            self.id = int (id)
            self.filetype = filetype
            if self.filetype not in self.accepted_filetypes:
                self.filetype = None
                raise ValueError
        except (KeyError, ValueError):
            raise cherrypy.HTTPError (400, 'Bad Request. Invalid parameters')


    def get_dc (self):
        """ Get a DublinCore struct for the ebook. """
        dc = BaseSearcher.DC (cherrypy.engine.pool)
        dc.load_from_database (self.id)
        # dc.translate ()
        return dc


    def get_extension (self):
        """ Get the ebook filename extension. """
        ext = self.filetype.split ('.', 1)[0]
        if ext == 'kindle' or ext == 'kf8':
            ext = 'mobi'
        elif ext == 'epub3':
            ext = '3.epub'
        return ext


    def get_filename (self):
        """ Get a suitable filename to store the ebook. """
        filename = self.get_dc ().make_pretty_title () + '.' + self.get_extension ()
        return filename.replace (':', '_')


    def get_source_url (self):
        """ Return the url of the ebook file on gutenberg.org. """
        protocol = 'https://' if cherrypy.config['host_https'] else 'http://'
        if self.id == 99999:
            # test filename
            return urllib.parse.urljoin (
                protocol + str(cherrypy.config['file_host']) , 'test.pdf')
        if self.filetype == 'pdf':
            return urllib.parse.urljoin (
                protocol + cherrypy.config['file_host'],
                'files/%d/%d-pdf.pdf' % (self.id, self.id))
        else:
            return urllib.parse.urljoin (
                protocol + cherrypy.config['file_host'],
                'ebooks/%d.%s' % (self.id, self.filetype))
