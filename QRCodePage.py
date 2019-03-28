#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
QRCodePage.py

Copyright 2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

A page to generate QR-codes.

"""

from __future__ import unicode_literals

import six
from six.moves import urllib

import cherrypy
import qrcode


class QRCodePage (object):
    """ Serve a QR-code as PNG image. """


    def index (self, **kwargs):
        """ Output QR-Code.

        Parameters are:

        data:     the data to encode (url quoted)
        ec_level: error correction level. One of:  L M Q H
        version:  QR code version
        box_size: size of one QR code box in pixel
        border:   width of border in boxes (should be at least 4)

        """

        qr = qrcode.QRCode (
            error_correction = self._get_ecl (kwargs),
            version          = kwargs.get ('version',  None),
            box_size         = kwargs.get ('box_size', 10),
            border           = kwargs.get ('border',   4),
        )

        qr.add_data (urllib.parse.unquote (kwargs['data']))
        qr.make (fit = True)

        img = qr.make_image ()

        cherrypy.response.headers['Content-Type'] = 'image/png'

        buf = six.BytesIO ()
        img._img.save (buf, 'PNG')
        return buf.getvalue ()


    @staticmethod
    def _get_ecl (kwargs):
        """ Get and decode error correction paramter. """

        ecl = {
            'L': 1,
            'M': 0,
            'Q': 3,
            'H': 2,
        }
        if 'ec_level' in kwargs and kwargs['ec_level'] in ecl:
            return ecl[kwargs['ec_level']]
        return ecl['M']
