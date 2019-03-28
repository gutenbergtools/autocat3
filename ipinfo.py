#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
ipinfo.py

Copyright 2013-14 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Find information about an IP, eg. hostname, whois, DNS blocklists.


The Spamhaus Block List (SBL) Advisory is a database of IP
addresses from which Spamhaus does not recommend the acceptance of
electronic mail.

The Spamhaus Exploits Block List (XBL) is a realtime database
of IP addresses of hijacked PCs infected by illegal 3rd party
exploits, including open proxies (HTTP, socks, AnalogX, wingate,
etc), worms/viruses with built-in spam engines, and other types of
trojan-horse exploits.

The Spamhaus PBL is a DNSBL database of end-user IP address
ranges which should not be delivering unauthenticated SMTP email
to any Internet mail server except those provided for specifically
by an ISP for that customer's use. The PBL helps networks enforce
their Acceptable Use Policy for dynamic and non-MTA customer IP
ranges.

"""

from __future__ import unicode_literals

import asyncdns

# pylint: disable=R0903

class DNSBL (object):
    """ Base class for DNS blocklists. """

    zone = ''
    blackhat_tags = {}
    dialup_tags = {}


### TOR ###
# see:
#   https://www.torproject.org/projects/tordnsel.html.en
#   https://www.dan.me.uk/dnsbl

class TorProject (DNSBL):
    """ A TOR exitnode list. """

    # note: reverse IP of www.gutenberg.org:80
    zone = '80.47.134.19.152.ip-port.exitlist.torproject.org'
    blackhat_tags = {
        '127.0.0.2': 'TOR',
    }

class TorDanme (DNSBL):
    """ A TOR exitnode list. """

    zone = 'torexit.dan.me.uk'
    blackhat_tags = {
        '127.0.0.100': 'TOR',
    }


### SPAMHAUS ###
# see: http://www.spamhaus.org/faq/answers.lasso?section=DNSBL%20Usage#202

class Spamhaus (DNSBL):
    """ A DNS blocklist. """

    zone = 'zen.spamhaus.org'
    blackhat_tags = {
        '127.0.0.2':  'SPAMHAUS_SBL',
        '127.0.0.3':  'SPAMHAUS_SBL_CSS',
        '127.0.0.4':  'SPAMHAUS_XBL_CBL',
    }
    dialup_tags = {
        '127.0.0.10': 'SPAMHAUS_PBL_ISP',
        '127.0.0.11': 'SPAMHAUS_PBL',
    }
    lookup = 'http://www.spamhaus.org/query/ip/{ip}'


### SORBS ###
# see: http://www.sorbs.net/using.shtml

class SORBS (DNSBL):
    """ A DNS blocklist. """

    zone = 'dnsbl.sorbs.net'
    blackhat_tags = {
        '127.0.0.2':  'SORBS_HTTP_PROXY',
        '127.0.0.3':  'SORBS_SOCKS_PROXY',
        '127.0.0.4':  'SORBS_MISC_PROXY',
        '127.0.0.5':  'SORBS_SMTP_RELAY',
        '127.0.0.6':  'SORBS_SPAMMER',
        '127.0.0.7':  'SORBS_WEB',             # formmail etc.
        '127.0.0.8':  'SORBS_BLOCK',
        '127.0.0.9':  'SORBS_ZOMBIE',
        '127.0.0.11': 'SORBS_BADCONF',
        '127.0.0.12': 'SORBS_NOMAIL',
    }
    dialup_tags = {
        '127.0.0.10': 'SORBS_DUL',
    }


### mailspike.net ###
# see: http://mailspike.net/usage.html

class MailSpike (DNSBL):
    """ A DNS blocklist. """

    zone = 'bl.mailspike.net'
    blackhat_tags = {
        '127.0.0.2':  'MAILSPIKE_DISTRIBUTED_SPAM',
        '127.0.0.10': 'MAILSPIKE_WORST_REPUTATION',
        '127.0.0.11': 'MAILSPIKE_VERY_BAD_REPUTATION',
        '127.0.0.12': 'MAILSPIKE_BAD_REPUTATION',
    }


### shlink.org ###
# see: http://shlink.org/

class BlShlink (DNSBL):
    """ A DNS blocklist. """

    zone = 'bl.shlink.org'
    blackhat_tags = {
        '127.0.0.2': 'SHLINK_SPAM_SENDER',
        '127.0.0.4': 'SHLINK_SPAM_ORIGINATOR',
        '127.0.0.5': 'SHLINK_POLICY_BLOCK',
        '127.0.0.6': 'SHLINK_ATTACKER',
    }

class DynShlink (DNSBL):
    """ A DNS dul list. """

    zone = 'dyn.shlink.org'
    dialup_tags = {
        '127.0.0.3': 'SHLINK_DUL',
    }


### barracudacentral.org ###
# see: http://www.barracudacentral.org/rbl/how-to-usee

class Barracuda (DNSBL):
    """ A DNS blocklist. """

    zone = 'b.barracudacentral.org'
    blackhat_tags = {
        '127.0.0.2':  'BARRACUDA_BLOCK',
    }


### SHADOWSERVER ###
# http://www.shadowserver.org/wiki/pmwiki.php/Services/IP-BGP

class ShadowServer (DNSBL):
    """ A DNS-based whois service. """

    zone      = 'origin.asn.shadowserver.org'
    peer_zone = 'peer.asn.shadowserver.org'
    fields    = 'asn cidr org2 country org1 org'.split ()


# TEAMCYMRU
# http://www.team-cymru.org/Services/ip-to-asn.html

class TeamCymru (DNSBL):
    """ A DNS-based whois service. """

    zone      = 'origin.asn.cymru.com'
    asn_zone  = 'asn.cymru.com'
    fields    = 'asn cidr country registry date'.split ()


class IPInfo (object):
    """ Holds DNSBL information for one IP. """

    dnsbl = [ Spamhaus, SORBS, MailSpike, BlShlink, DynShlink, Barracuda,
              TorProject, TorDanme ]
    """ Which blocklists to consider. """

    def __init__ (self, aresolver, ip):
        self.hostname      = None
        self.whois         = {}
        self.blackhat_tags = set ()
        self.dialup_tags   = set ()

        ip = str (ip)
        rr = asyncdns.adns.rr

        try:
            aresolver.query (ip, self._hostnamesetter (), rr.PTR)

            for dnsbl in self.dnsbl:
                aresolver.query_dnsbl (ip, dnsbl.zone, self._tagsetter  (dnsbl))

            # ShadowServer seems down: March 2014
            aresolver.query_dnsbl (ip, ShadowServer.zone, self._whoissetter_ss (), rr.TXT)
            # aresolver.query_dnsbl (ip, TeamCymru.zone,    self._whoissetter_tc (aresolver), rr.TXT)
        except:
            pass


    @property
    def tags (self):
        """ All tags (bad and dialup). """
        return self.blackhat_tags | self.dialup_tags


    def is_blackhat (self):
        """ Return true if this is probably a blackhat IP. """
        return bool (self.blackhat_tags)


    def is_dialup (self):
        """ Test if this IP is a dialup. """
        return bool (self.dialup_tags)


    def is_tor_exit (self):
        """ Test if this is a Tor exit node. """
        return 'TOR' in self.blackhat_tags


    def _hostnamesetter (self):
        """ Return a callable object that puts the answer into
        the hostname attribute. """
        def g (answer):
            """ Store answer. """
            self.hostname = answer[0]
        return g


    @staticmethod
    def _filter (answers, tag_dict):
        """ Lookup answers in tag_dict, return values of matches. """
        return [ tag_dict[ip] for ip in answers if ip in tag_dict ]


    def _tagsetter (self, dnsbl):
        """ Return a callable object that puts the answer into
        our *tags attributes. """
        def g (answer):
            """ Store answer. """
            self.blackhat_tags.update (self._filter (answer, dnsbl.blackhat_tags))
            self.dialup_tags.update   (self._filter (answer, dnsbl.dialup_tags))
        return g


    @staticmethod
    def _decode_txt (answer):
        """ Helper: decode / unpack whois answer. """
        try:
            answer = answer[0][0].decode ('utf-8')
        except UnicodeError:
            answer = answer[0][0].decode ('iso-8859-1')
        answer = answer.strip ('"').split ('|')
        return [ a.strip () for a in answer if a ]


    def _whoissetter_ss (self):
        """ Return a callable object that puts the answer into
        the whois dict. """
        def g (answer):
            """ Store answer. """
            self.whois = dict (zip (ShadowServer.fields, self._decode_txt (answer)))
        return g


    def _whoissetter_tc (self, aresolver):
        """ Return a callable object that puts the answer into
        the right attribute. """
        def g (answer):
            """ Store answer. """
            self.whois = dict (zip (TeamCymru.fields, self._decode_txt (answer)))
            self.whois['org'] = None
            # maybe there's still more info?
            aresolver.query ('AS' + self.whois['asn'] + '.' + TeamCymru.asn_zone,
                             self._whoissetter_tc2 (), asyncdns.adns.rr.TXT)
        return g


    def _whoissetter_tc2 (self):
        """ Return a callable object that puts the answer into
        the right attribute. """
        def g (answer):
            """ Store answer. """
            self.whois['org'] = self._decode_txt (answer)[-1]
        return g



if __name__ == '__main__':
    import sys

    # test IP 127.0.0.2 should give all positives

    a = asyncdns.AsyncDNS (asyncdns.RESOLV_CONF)
    i = IPInfo (a, sys.argv[1])
    a.wait ()
    a.cancel ()

    print ('hostname: %s' % i.hostname)
    for k in sorted (i.whois.keys ()):
        print ("%s: %s" % (k, i.whois[k]))
    for tag in sorted (i.tags):
        print (tag)
    if i.is_blackhat ():
        print ('BLACKHAT')
    if i.is_dialup ():
        print ('DUL')
