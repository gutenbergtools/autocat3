#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
asyncdns.py

Copyright 2013-14 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

Higher level interface to the GNU asynchronous DNS library.

"""

from __future__ import unicode_literals

import sys
import time

import adns

# pass this to __init__ to use Google Public DNS
RESOLV_CONF = 'nameserver 8.8.8.8'

# http://www.ietf.org/rfc/rfc1035.txt Domain Names
# http://www.ietf.org/rfc/rfc3490.txt IDNA
# http://www.ietf.org/rfc/rfc3492.txt Punycode

class AsyncDNS (object):
    """ An asynchronous DNS resolver. """

    def __init__ (self, resolv_conf = None):
        if resolv_conf:
            self.resolver = adns.init (
                adns.iflags.noautosys + adns.iflags.noerrprint,
                sys.stderr, # FIXME: adns version 1.2.2 will allow keyword params
                resolv_conf)
        else:
            self.resolver = adns.init (
                adns.iflags.noautosys + adns.iflags.noerrprint)

        self._queries = {} # keeps query objects alive

    def query (self, query, callback, rr = adns.rr.A):
        """ Queue a query.

        :param query: the query string (may contain unicode characters)
        :param callback: function taking a tuple of answers
        :param rr: the query rr type code

        """

        if rr not in (adns.rr.PTR, adns.rr.PTRraw):
            query = self.encode (query)
        if rr in (adns.rr.PTR, adns.rr.PTRraw):
            self._queries [self.resolver.submit_reverse (query, rr)] = callback, rr
        else:
            self._queries [self.resolver.submit (query, rr)] = callback, rr

    def query_dnsbl (self, query, zone, callback, rr = adns.rr.A):
        """ Queue a reverse dnsbl-type query. """
        self._queries [self.resolver.submit_reverse_any (query, zone, rr)] = callback, rr

    def done (self):
        """ Are all queued queries answered? """
        return not self._queries

    def wait (self, timeout = 10):
        """ Wait for the queries to complete. """

        timeout += time.time ()
        while self._queries and time.time () < timeout:
            for q in self.resolver.completed (1):
                answer = q.check ()
                callback, rr = self._queries[q]
                del self._queries[q]

                # print (answer)

                a0 = answer[0]
                if a0 == 0:
                    callback (self.decode_answer (rr, answer[3]))
                elif a0 == 101 and rr == adns.rr.A:
                    # got CNAME, wanted A: resubmit
                    self.query (answer[1], callback, rr)
                # else
                #   pass


    def decode_answer (self, rr, answers):
        """ Decode the answer to unicode.

        Supports only some rr types. You may override this to support
        some more.

        """

        if rr in (adns.rr.A, adns.rr.TXT):
            # A records are ip addresses that need no decoding.
            # TXT records may be anything, even binary data,
            # so leave decoding to the caller.
            return answers

        if rr in (adns.rr.PTR, adns.rr.PTRraw, adns.rr.CNAME, adns.rr.NSraw):
            return [ self.decode (host) for host in answers ]

        if rr == adns.rr.MXraw:
            return [ (prio, self.decode (host)) for (prio, host) in answers ]

        if rr == adns.rr.SRVraw:
            return [ (prio, weight, port, self.decode (host))
                     for (prio, weight, port, host) in answers ]

        if rr in (adns.rr.SOA, adns.rr.SOAraw):
            return [ (self.decode (mname), self.decode (rname),
                      serial, refresh, retry, expire, minimum)
                     for (mname, rname, serial, refresh,
                          retry, expire, minimum) in answers ]

        # unsupported HINFO, RP, RPraw, NS, SRV, MX

        return answers


    @staticmethod
    def encode (query):
        """ Encode a unicode query to idna.

        Result will still be of type unicode/str.
        """
        return query.encode ('idna').decode ('ascii')


    @staticmethod
    def decode (answer):
        """ Decode an answer to unicode. """
        try:
            return answer.decode ('idna')
        except ValueError:
            return answer.decode ('ascii', 'replace')


    def cancel (self):
        """ Cancel all pending queries. """

        for q in self._queries.keys ():
            q.cancel ()
        self._queries.clear ()


    def bulk_query (self, query_dict, rr):
        """ Bulk lookup.

        :param dict: on entry { query1: None,        query2: None    }
                     on exit  { query1: (answer1, ), query2: (answer2a, answer2b) }

        Note: you must call wait () after bulk_query () for the answers to appear

        """

        def itemsetter (query):
            """ Return a callable object that puts the answer into
            the dictionary under the right key. """
            def g (answer):
                """ Put the answer into the dictionary. """
                query_dict[query] = answer
                # print "put: " + answer
            return g

        for query in query_dict.keys ():
            if query:
                self.query (query, itemsetter (query), rr)


def bulk_query (dict_, rr = adns.rr.A, timeout = 10):
    """ Perform bulk lookup. """
    a = AsyncDNS ()
    a.bulk_query (dict_, rr)
    a.wait (timeout)
    a.cancel ()


if __name__ == '__main__':
    import netaddr

    queries = dict ()
    for i in range (64, 64 + 32):
        ip = '66.249.%d.42' % i # google assigned netblock
        queries[ip] = None

    bulk_query (queries, adns.rr.PTR)

    ipset = netaddr.IPSet ()
    for ip in sorted (queries):
        if queries[ip] and 'proxy' in queries[ip][0]:
            print (ip)
            ipset.add (ip + '/24')

    for cidr in ipset.iter_cidrs ():
        print (cidr)
