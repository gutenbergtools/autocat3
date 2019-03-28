#!/usr/bin/env python
#  -*- mode: python; indent-tabs-mode: nil; -*- coding: utf-8 -*-

"""
RateLimiter.py

Copyright 2010-2014 by Marcello Perathoner

Distributable under the GNU General Public License Version 3 or newer.

A very basic IP rate limiter tool for cherrypy.


begin;
drop table robots.blocks;
create table robots.blocks (
   ip             cidr      primary key,
   host           text      default null,
   has_info       boolean   default false,
   is_blocked     boolean   default true,
   is_whitelisted boolean   default false,
   created        timestamp default now (),
   expires        timestamp default null,
   types          text[]    default null,
   org            text      default null,
   country        text      default null,
   note           text      default null,
   whois          text      default null,
   user_agents    text[]    default null,
   requests       text[]    default null
);


"""

from __future__ import unicode_literals

import datetime
import re
import logging
import threading
import random
import collections
import itertools

import cherrypy
import requests
import netaddr

from libgutenberg.GutenbergDatabase import DatabaseError
import BaseSearcher
import Page
import asyncdns
import ipinfo

# no. of requests to keep in LIFO queue for each IP
KEEP_REQUESTS = 10

RE_SPOOFED_BOTS = re.compile (
    'Googlebot|msnbot|bingbot|Yahoo! Slurp|YandexBot|Baiduspider|ia_archiver')

TRUSTED_XFF_URL = "https://meta.wikimedia.org/w/extensions/TrustedXFF/trusted-hosts.txt"


def log (ip, msg, context = 'RATELIMITER', severity = logging.INFO):
    """ Log with IP. """

    a = []
    if ip:
        a.append (str (ip))
    if msg:
        a.append (str (msg))

    cherrypy.log (' '.join (a), context = context, severity = severity)


def to_cidr (ip):
    """ Build cidr out of ip. """

    if ip and ip != 'unknown':
        if ':' in ip:
            return str (ip) + '/128'
        return str (ip) + '/32'
    return None


# See: https://docs.python.org/3/library/itertools.html
def unique_everseen (iterable):
    "List unique elements, preserving order. Remember all elements ever seen."
    # unique_everseen('AAAABBBCCDAABBB') --> A B C D
    # unique_everseen('ABBCcAD', str.lower) --> A B C D
    seen = set ()
    seen_add = seen.add
    for element in itertools.filterfalse (seen.__contains__, iterable):
        seen_add (element)
        yield element


class IPStruct (object):
    """ A container for a client and proxy address. """

    def __init__ (self):
                                    # ips are always of type string
        self.client_ip = None       # ip of client (or of untrusted proxy)
        self.proxy_ip = None        # ip of proxy or None
        self.proxy_type = None      # None, 'anonymous', 'untrusted', 'trusted', 'private'
        self.whitelisted = False    # if whitelisted ip (eg. Googlebot)
        self.ipinfo = None          # more (dns, whois) info about this ip


    def from_request (self, request, rl):
        """ Init from remote IP and X-Forwarded-For header. """

        xffh = request.headers.get ('X-Forwarded-For') or "%s, %s" % (
            cherrypy.request.remote.ip, cherrypy.request.remote.ip)

        log ('X-FORWARDED-FOR', xffh)

        # split string header into array of IPs
        xff = [x.strip () for x in xffh.split (',')]

        # strip ibiblio haproxy IP
        xff = [x for x in xff if not x.startswith ("2610:28:3091:3001:")]

        xff = list (reversed (list (unique_everseen (xff))))
        if not xff:
            xff = [cherrypy.request.remote.ip]

        try:
            nip = netaddr.ip.IPAddress (xff[0])
        except netaddr.AddrFormatError:
            raise cherrypy.HTTPError (400, 'Bad Request. Invalid IP: %s.' % xff[0])

        self.whitelisted = nip in rl.whitelist

        # the request reaches the app server either this way:
        #
        #   user_proxy* haproxy varnish mod_proxy app_server
        #
        # or this way:
        #
        #   user_proxy* haproxy varnish php_curl app_server
        #
        # so the layout of xff is either:
        #
        # xff[0] address of user    (added by curl)
        # xff[1] address of haproxy (added by varnish)
        # xff[2] address of user    (added by haproxy)
        # xff[3] address of user    (added by user_proxy)
        #
        # or
        #
        # xff[0] address of user    (added by mod_proxy)
        # xff[1] address of haproxy (added by varnish)
        # xff[2] address of user    (added by haproxy)
        # xff[3] address of user    (added by user_proxy)

        self.client_ip = xff[0]
        offset = 1
        if len (xff) >= 2 and xff[0] == xff[1]:
            # skip identic ip
            offset = 2
        if len (xff) > offset:
            # some kind of proxy detected
            self.client_ip = xff[offset]
            self.proxy_ip  = xff[0]

            if self.client_ip == 'unknown':
                self.proxy_type = 'anonymous'
            else:
                try:
                    if netaddr.ip.IPAddress (self.client_ip).is_private ():
                        self.proxy_type = 'private'
                except netaddr.AddrFormatError:
                    raise cherrypy.HTTPError (400, 'Bad Request. Invalid IP: %s.' % self.client_ip)

            if self.proxy_type is None:
                # Check if this request came through a trusted proxy.
                # This check is expensive, so do it only if needed.
                if nip in rl.trusted_xff_list:
                    self.proxy_type = 'trusted'
                else:
                    self.proxy_type = 'untrusted'


    def get_cache_key (self):
        """ Make a key suitable for caching an ipsession.

        This key will distinguish users.

        """
        if self.proxy_type == 'trusted':
            return "%s-%s" % (self.proxy_ip, self.client_ip)
        else:
            return self.proxy_ip or self.client_ip


    def get_ip_to_block (self):
        """ Get the IP to block.

        Because we use apache 'deny from' to block, we need
        the proxy address, not the address behind the proxy.

        """
        return self.proxy_ip or self.client_ip


    def sort_key (self):
        """ Return a key for sorting of IPStructs. """
        return netaddr.ip.IPAddress (self.get_ip_to_block ()).sort_key ()


    def __str__ (self):
        """ Return a human-readable representation. """
        if self.proxy_ip:
            return "%s via %s (%s)" % (self.client_ip, self.proxy_ip, self.proxy_type)
        return self.client_ip


class RatelimiterSession (dict):
    """ A session maintained for every remote IP. """

    def __init__ (self, rl, ips):
        super (RatelimiterSession, self).__init__ ()

        self.ips = ips
        self.sessions = set ()
        now = datetime.datetime.now ()

        # pylint: disable=too-many-function-args
        self.update (
            {
                'blocked':     0,                  # 1 = temp, 2 = perm, 9 = written to db
                'expires':     now,                # expiration of this session
                'last_hit':    now,                # time of last hit
                'hits':        0,                  # all hits
                'rhits':       0,                  # ip score
                'rhits_max':   rl.rhits_max,       # next captcha appears at this score
                'captchas':    0,                  # no. of captchas presented
                'rearms':      0,                  # how many times rearmed (thru captcha)
                'dhits':       0,                  # denied hits
                'user_agents': set (),             # all user agents seen from this ip
                'signatures':  set (),             # all http signatures seen from this ip
                'requests':    collections.deque ([], KEEP_REQUESTS), # last n requests
                'referrers':   collections.deque ([], KEEP_REQUESTS), # last n referrers
                'categories':  collections.deque ([], KEEP_REQUESTS), # last n categories
                'headers':     [],                 # request headers
                'active':      True,               # for stats page
                'css_ok':      None,               # flag for stats page
                'expire_days': 1,                  # expiration of block
            }
        )

        self.set_expiration (rl.expiration)


    def append_trace (self, rl, ua, signature):
        """ Append trace of last X requests. """

        headers = cherrypy.request.headers

        session = cherrypy.session

        ipset = session.get ('ips', set ())
        ipset.add (self.ips.client_ip)
        session['ips'] = ipset

        uaset = session.get ('user_agents', set ())
        uaset.add (ua)
        session['user_agents'] = uaset

        self['signatures'].add (signature)

        request_str = headers.get ('X-Request')
        if request_str is None:
            request_str = cherrypy.request.path_info
            if cherrypy.request.query_string:
                request_str += '?' + cherrypy.request.query_string
        request_str = request_str[:100]
        self['requests'].append (request_str)
        self['referrers'].append (headers.get ('Referer'))

        # categorize request
        for cat in rl.categories:
            if request_str.startswith (cat):
                self['categories'].append (cat)
                break


    def set_add_with_trigger (self, set_, value, trigger_size):
        """ Insert value into set and trigger on size. """

        if value in set_:
            return False
        set_.add (value)
        return len (set_) == trigger_size


    def calc_block (self, rl, ua):
        """ Calculate the penalties for this hit.

        Penalties make rhits grow faster, thus captchas come earlier.

        """

        headers = cherrypy.request.headers
        session = cherrypy.session
        path = cherrypy.request.path_info
        now = datetime.datetime.now ()

        self['rhits'] += 1

        # penalties
        if self['last_hit'] + datetime.timedelta (seconds = rl.min_interval) > now:
            self['rhits'] += rl.rate_malus

        # new session?
        if 'captchas' not in session:
            self['rhits'] += rl.session_malus
            session['captchas'] = 0
        elif session['captchas'] == 0:
            self['rhits'] += rl.no_captcha_malus

        if ('.opds' not in path) and ('.stanza' not in path):
            if self.has_few ('referrers'):
                self['rhits'] += rl.referrer_malus

            if self.has_few ('categories'):
                self['rhits'] += rl.category_malus

            if 'Accept-Encoding' not in headers:
                self['rhits'] += rl.encoding_malus

            if self['css_ok'] == False: # 3-state logic
                self['rhits'] += rl.css_malus

        penalty = headers.get ('X-Penalize-Me')
        if penalty is not None:
            self['rhits'] += max (int (penalty), 1)

        if 'X-Error-404' in headers:
            self['rhits'] += rl.e404_malus

        # soft block to captcha
        if self['blocked'] == 0:
            if self['rhits'] >= self['rhits_max']:
                self['blocked'] = 1

            if self.set_add_with_trigger (self['user_agents'], ua, 5):
                if len (self['signatures']) <= 3:
                    self.log ('Captcha on too few http header signatures')
                    self['blocked'] = 1

        if self['blocked'] == 1:
            if self['rearms'] > rl.rearms_max:
                self.log ('Blocked on rearms_max')
                self['blocked'] = 2

        # hard block
        if self['blocked'] < 2:
            if self['captchas'] > rl.captchas_max:
                self.log ('Blocked on captchas_max')
                self['blocked'] = 2

            penalty = headers.get ('X-Block-Me')
            if penalty is not None:
                self.log ('Blocked on X-Block-Me')
                self['blocked'] = 2
                self['expire_days'] = max (int (penalty), 1)

            if len (session['user_agents']) > rl.ua_limit:
                # spoofed random user-agents
                self.log ('Blocked on session ua_limit')
                self['blocked'] = 2

            if len (session['ips']) > rl.ip_limit:
                # session from multiple ips (probably proxies)
                self.log ('Blocked on session ip_limit')
                self['blocked'] = 2

            if (ua is not None) and (RE_SPOOFED_BOTS.search (ua) is not None):
                # spoofed user-agent because not from whitelisted ip
                self.log ('Blocked on spoofed user agent')
                self['blocked'] = 2

            # if self.ips.proxy_type == 'anonymous':
            #     self.log ('Blocked on anon_proxy')
            #     self['blocked'] = 2


    def extend_expiration (self, timeout):
        """ Extend expiration time to now + timeout. """

        new_expires = datetime.datetime.now () + datetime.timedelta (seconds = timeout)
        self['expires'] = max (new_expires, self['expires'])


    def set_expiration (self, timeout):
        """ Set expiration time to now + timeout. """

        new_expires = datetime.datetime.now () + datetime.timedelta (seconds = timeout)
        self['expires'] = new_expires


    def has_few (self, what):
        """ IPs that always use the same referrer or always hit the
        same category are most likely bots. """

        return self['hits'] > KEEP_REQUESTS and len (set (list (self[what]))) < 2


    def get_tags (self):
        """ Get all tags from ipinfo and add oir own. """
        tags = list (self.ips.ipinfo.tags)
        if self['css_ok'] == False: # 3-state
            tags.append ('NO_CSS')
        return sorted (tags)


    def captcha_answer (self, response):
        """ Check answer to captcha. """

        if response.is_valid:
            # session.captchas NOT ipsession.captchas
            captchas = cherrypy.session.get ('captchas', 0)
            cherrypy.session['captchas'] = captchas + 1
            self.rearm ()
            self.log ('Correct answer', 'CAPTCHA')
        else:
            self.log ('Wrong answer', 'CAPTCHA')


    def rearm (self):
        """ Rest counters. """

        rl = cherrypy.tools.rate_limiter # pylint: disable=E1101

        if self['blocked'] < 2 and self['rearms'] <= rl.rearms_max:
            self.log ('Rearmed')
            self['rearms'] += 1
            self['blocked'] = 0
            self['captchas'] = 0
            # recharge, but don't add up multiple recharges
            self['rhits_max'] = min (self['rhits'] + rl.rhits_max,
                                     self['rhits_max'] + rl.rhits_max)
            self.set_expiration (rl.expiration)


    def block_me (self):
        """ Immediately block this IP. """

        self.log ('Blocked on block_me')
        self['blocked'] = 2


    def unblock_me (self):
        """ Unblock this IP. """

        self.rearm ()


    def log (self, msg, context = 'RATELIMITER'):
        """ Log with IP. """

        log (str (self.ips), str (msg), context)


    def log_state (self):
        """ Log the session state. """

        tup = (
            self['blocked'],
            self['hits'],
            self['rhits'],
            self['rhits_max'],
            self['requests'][-1],
            )
        self.log ("%d %d %d/%d %s" % tup)

        if 'is-catalog-maintainer' in cherrypy.request.cookie:
            cherrypy.response.headers['X-Ratelimiter-Info'] = "b:%d h:%d %d/%d %s" % tup


class RateLimiterTool (cherrypy.Tool):
    """ Limit rate of access per IP. """

    lock = threading.Lock ()
    dblock = threading.Lock () # database accesses
    cache = {}

    # http header fields that should change if user-agent changes,
    # but bots that spoof user-agent won't bother to randomize

    http_headers_no_random = set (
        """Accept Accept-Language Accept-Charset Accept-Encoding
        Cache-Control Connection Dnt Keep-Alive Pragma"""
        .split ())

    http_headers_ignore = set (
        """X-Forwarded-For X-Forwarded-Server X-Forwarded-Host
        X-Request X-Varnish X-Block-Me X-Penalize-Me Remote-Addr
        Cookie"""
        .split ())

    def __init__ (self):
        """ Initialize the Rate Limiter.

        Needs to be on before_request_body on priority > 30 because
        tools.proxy (on prio 30) needs a chance to rewrite the IP.

        """

        super (RateLimiterTool, self).__init__ ('before_request_body', None)
        self.callable = self.limit
        self._priority = 60

        conf = cherrypy.config.get

        # ipsession expiration in seconds
        self.expiration       = conf ('tools.rate_limiter.expiration',      30 * 60)

        # cleanup thread frequency
        self.frequency        = conf ('tools.rate_limiter.frequency',       60)

        # when rhits are reached a captcha must be solved
        self.rhits_max        = conf ('tools.rate_limiter.rhits_max',       500)

        # this many captchas are presented before hard block
        self.captchas_max     = conf ('tools.rate_limiter.captchas_max',    10)

        # how many times rearm thru captcha works
        self.rearms_max       = conf ('tools.rate_limiter.rearms_max',      20)

        # more than this many user agents on *session* will get ip blocked
        self.ua_limit         = conf ('tools.rate_limiter.ua_limit',         4)

        # more than this many ips on *session* will get ip blocked
        self.ip_limit         = conf ('tools.rate_limiter.ip_limit',        20)

        # leave this much time between requests or get rate_malus
        self.min_interval     = conf ('tools.rate_limiter.min_interval',     1)

        self.session_malus    = conf ('tools.rate_limiter.session_malus',   20)
        self.no_captcha_malus = conf ('tools.rate_limiter.no_captcha_malus', 1)
        self.e404_malus       = conf ('tools.rate_limiter.e404_malus',     200)
        self.rate_malus       = conf ('tools.rate_limiter.rate_malus',      10)
        self.encoding_malus   = conf ('tools.rate_limiter.encoding_malus',   5)
        self.referrer_malus   = conf ('tools.rate_limiter.referrer_malus',   5)
        self.category_malus   = conf ('tools.rate_limiter.category_malus',   0)
        self.css_malus        = conf ('tools.rate_limiter.css_malus',        0)

        self.whitelist        = self.load_whitelist (conf)
        self.trusted_xff_list = self.load_trusted_xff_list (conf)

        self.users = 0           # no. of active users
        self.hits = 0            # no. of hits
        self.whitelist_hits = 0  # no. of hits from whitelisted ips
        self.denied_hits = 0     # no. of denied accesses

        self.hit_accumulator = 0
        self.whitelist_hit_accumulator = 0
        self.denied_hit_accumulator = 0

        self.categories = '/ebooks/search/ /ebooks/ /files/ /cache/'.split ()

        # reasons
        # suggest: ajax call, user cannot see the captcha
        # captcha: user must see captcha even if soft-blocked
        # stats: don't block the sysop
        # re must match whole path !
        self.whitelisted_paths = re.compile (r'/ebooks/suggest/|/stats/|/w/captcha/.*')


    @staticmethod
    def load_whitelist (conf):
        """ Load IP whitelist. """

        wl = netaddr.ip.sets.IPSet ()
        for cidr in conf ('tools.rate_limiter.whitelist', '').splitlines ():
            cidr = cidr.partition ('#')[0]
            cidr = cidr.strip ()
            if cidr:
                wl.add (netaddr.ip.IPNetwork (cidr))
                # print cidr
        return wl


    @staticmethod
    def load_trusted_xff_list (conf):
        """ Load a list of proxies whose X-Forwarded-For header we trust. """

        tl = netaddr.ip.sets.IPSet ()
        try:
            url = conf ('tools.rate_limiter.trusted_xff_url')
            if url:
                log (None, "Requesting trusted xff list from: %s ..." % url)
                trusted_xff_list = requests.get (url)
                log (None, "Scanning trusted xff list ...")
                cidrs = []
                to_resolve = {}
                skip = True # horrible hack to skip AOL proxies in list
                for line in trusted_xff_list.text.splitlines ():
                    if line.startswith ('# British Columbia school network'):
                        skip = False
                    if skip:
                        continue
                    line = line.partition ('#')[0]
                    line = line.strip ()
                    if line:
                        try:
                            cidr = netaddr.ip.IPNetwork (line)
                            cidrs.append (cidr)
                        except (ValueError, netaddr.core.AddrFormatError):
                            # not an IP, maybe a hostname we can resolve
                            to_resolve[line] = None
                trusted_xff_list.close ()
                tl.update (cidrs)
                if to_resolve:
                    log (None, "Resolving hosts in xff list ...")
                    asyncdns.bulk_query (to_resolve, asyncdns.adns.rr.A, 5)
                    tl.update ( (ip[0] for ip in to_resolve.values () if ip is not None) )

        except Exception as what:
            log (None, what)

        for cidr in conf ('tools.rate_limiter.trusted_xff_list', '').splitlines ():
            cidr = cidr.partition ('#')[0]
            cidr = cidr.strip ()
            if cidr:
                tl.add (netaddr.ip.IPNetwork (cidr))
                # print cidr

        log (None, "Loaded {count} trusted xff ips.".format (count = len (tl)))
        return tl


    def e404 (self):
        """ 404 penalty when hitting non-existing ebook nos.
        for people who write naive scraper scripts. """
        cherrypy.ipsession['rhits'] += self.e404_malus


    def block (self, ip):
        """ Block IP. """

        ipsession = self.cache.get (ip)
        if ipsession is not None:
            ipsession.block_me ()
            return True
        return False


    def unblock (self, ip):
        """ Unblock IP. """

        ipsession = self.cache.get (ip)
        if ipsession is None:
            return False

        ipsession.unblock_me ()

        conn = cherrypy.engine.pool.connect ()
        c  = conn.cursor ()
        with self.dblock:
            try:
                c.execute ('begin')
                c.execute ('set transaction isolation level serializable')
                query = 'UPDATE robots.blocks SET expires = now () WHERE ip = %(ip)s'
                params = { 'ip': to_cidr (ip) }
                c.execute (query, params)
                c.execute ('commit')
            except DatabaseError as what:
                cherrypy.log ("SQL Error: %s\n" % what,
                              context = 'RATELIMITER', severity = logging.ERROR)
                cherrypy.log ("Query was: %s\n" % c.mogrify (query, params),
                              context = 'RATELIMITER', severity = logging.ERROR)
                c.execute ('rollback')

        return True


    @staticmethod
    def get_challenge ():
        """ Generate a challenge. Called from genshi templates. """

        # currently the challenge gets applied as xml id
        challenge = cherrypy.session['challenge'] = 'id' + str (random.randint (1000, 9999))
        return challenge


    @staticmethod
    def check_challenge ():
        """ User agent handles cookies, JS and CSS if answer equals challenge. """

        # Note that we cannot insert a challenge into every html page,
        # only in those the app server generates. Thus we may get back
        # the answer cookie for one challenge more than once.

        s = cherrypy.session
        if 'challenge' not in s:
            return None # no challenge emitted yet
        cookies = cherrypy.request.cookie
        if 'bonus' not in cookies:
            return False

        challenge = s['challenge']
        answer = cookies['bonus'].value

        if 'is-catalog-maintainer' in cookies:
            # send some debug info
            cherrypy.response.headers['X-CSS-Bonus'] = (
                "Challenge: %s - Response: %s" % (challenge, answer))

        return answer == challenge


    def _get_ip_session (self):
        """ Retrieve or create an ipsession for this request. """

        ips = IPStruct ()
        ips.from_request (cherrypy.request, self)

        # get or set ipsession object
        cache_key = ips.get_cache_key ()
        try:
            ipsession = self.cache[cache_key]
        except KeyError:
            ipsession = RatelimiterSession (self, ips)
            # To guard against `list (dict.items ())` failing in
            # `self.reset ()` because of 'RuntimeError: dictionary
            # changed size during iteration'
            with self.lock:
                self.cache[cache_key] = ipsession

        return ipsession


    def _get_headers_array (self, headers):
        """ All request headers in one array of string. """

        a = []
        for k, v in headers.items ():
            a.append (k + ': ' + v)
        return a


    def _get_http_signature (self, headers):
        """ Get a signature of the header fields.

        Rationale: to detect randomly spoofed user-agents we
        check if the signature stays the same over a range of
        (possibly spoofed) user-agents.

        """

        a = []
        for k, v in headers.items ():
            if k in self.http_headers_ignore or k.startswith ('X-'):
                continue
            if k in self.http_headers_no_random:
                a.append (k + ': ' + v)
            else:
                a.append (k)
        # FIXME: we have no way of getting the header order
        # coordinate with ibiblio varnish team?
        # FIXME: just return a hash after debugging this
        return '|'.join (sorted (a))


    def limit (self, **dummy_kwargs):
        """ Do accounting for ip and return 403 if ip exceeded quota. """

        ipsession = self._get_ip_session ()

        cherrypy.serving.ipsession = ipsession
        if not hasattr (cherrypy, "ipsession"):
            cherrypy.ipsession = cherrypy._ThreadLocalProxy ('ipsession') # pylint: disable=W0212

        ipsession.sessions.add (cherrypy.session.id)

        headers = cherrypy.request.headers

        ua = headers.get ('User-Agent')
        signature = self._get_http_signature (headers)

        whitelisted = (ipsession.ips.whitelisted or
                       self.whitelisted_paths.match (cherrypy.request.path_info))

        with self.lock:
            ipsession['active'] = True
            ipsession.extend_expiration (self.expiration)
            ipsession.append_trace (self, ua, signature)
            ipsession['css_ok'] = self.check_challenge () # store value for stats page

            if not whitelisted:
                ipsession.calc_block (self, ua)

            ipsession['last_hit'] = datetime.datetime.now () # set this after calc_block
            ipsession.log_state ()

            # allow hit
            if whitelisted:
                ipsession.log ('whitelisted')
                cherrypy.response.headers['X-Whitelisted'] = 'ratelimiter'
                ipsession['hits'] += 1
                self.whitelist_hit_accumulator += 1
                return

            if ipsession['blocked'] == 0:
                ipsession['hits'] += 1
                self.hit_accumulator += 1
                return

            # soft or hard deny
            self.denied_hit_accumulator += 1
            cherrypy.lib.caching.expires (0, True)

            if ipsession['blocked'] == 1:
                ipsession['captchas'] += 1
                ipsession.extend_expiration (10 * self.expiration) # watch 'em longer
                ipsession.log ('Redirected to captcha')
                cherrypy.response.headers['X-Ratelimiter-Denied'] = "503"
                raise cherrypy.HTTPRedirect ('//www.gutenberg.org/w/captcha/question/')
            else:
                ipsession['dhits'] += 1
                ipsession.set_expiration (self.expiration)
                if not ipsession['headers']:
                    ipsession['headers'] = self._get_headers_array (headers)
                ipsession.log ('Blocked 403')
                cherrypy.response.headers['X-Ratelimiter-Denied'] = "403"
                raise cherrypy.HTTPError (403, 'Forbidden')


    def reset (self):
        """ Reset the hit counters. """

        try:
            users = 0
            now = datetime.datetime.now ()
            active_window = now - datetime.timedelta (seconds = 60)

            # To guard against `list (self.cache.items ())` failing because
            # of 'RuntimeError: dictionary changed size during iteration'
            with self.lock:
                sessions = list (self.cache.items ())

            # We have to lock self.cache while deleting items, so to keep
            # the lock short, we first compute a list of keys to delete.
            expired_keys = []
            for key, data in sessions:
                if data['expires'] < now:
                    expired_keys.append (key)
                if data['last_hit'] < active_window:
                    data['active'] = False
                if data['active']:
                    users += 1

            with self.lock:
                for key in expired_keys:
                    try:
                        del self.cache[key]
                    except KeyError:
                        cherrypy.log ('KeyError in reset ()', context = 'RATELIMITER',
                                      severity = logging.ERROR)
                self.users = users
                self.hits = self.hit_accumulator
                self.whitelist_hits = self.whitelist_hit_accumulator
                self.denied_hits = self.denied_hit_accumulator

                self.hit_accumulator = 0
                self.whitelist_hit_accumulator = 0
                self.denied_hit_accumulator = 0

            BaseSearcher.formats_acc.reset ()
            BaseSearcher.formats_sum_acc.reset ()

            cherrypy.log ('Run reset ()', context = 'RATELIMITER', severity = logging.INFO)

        except Exception as what:
            # make sure background thread never stops
            cherrypy.log ("Error in reset (): %s" % what,
                          context = 'RATELIMITER', severity = logging.ERROR)


    def debug_reset_all (self):
        """ Reset all hit counters unconditionally.

        Used only by the test suite.

        """
        for key in list (self.cache.keys ()):
            try:
                del self.cache[key]
            except KeyError:
                pass
        cherrypy.log ('Run debug_reset_all ()', context = 'RATELIMITER', severity = logging.INFO)



    @staticmethod
    def get_ipinfo_for (sessions):
        """ Retrieve IP info for all sessions.

        Retrieves info asynchronously in parallel for all sessions.

        """

        adns = asyncdns.AsyncDNS (asyncdns.RESOLV_CONF)
        for ipsession in sessions:
            try:
                if ipsession.ips.ipinfo is None:
                    ip = ipsession.ips.get_ip_to_block ()
                    ipsession.ips.ipinfo = ipinfo.IPInfo (adns, ip)
            except Exception as what:
                cherrypy.log ("Error in get_ipinfo_for (): %s" % what,
                              context = 'RATELIMITER', severity = logging.ERROR)
        adns.wait ()
        adns.cancel ()


    @staticmethod
    def ua_decode (ua):
        """ Try if we can upgrade the encoding to utf-8.

        'headers' items are already decoded to unicode by
        cherrypy, but I found that many foreign (chinese) user
        agents use but fail to specify the utf-8 encoding, so
        that cherrypy wrongly decodes from iso-8859-1.
        """

        if ua is None:
            return 'NO_UA'
        try:
            return ua.encode ('iso-8859-1').decode ('utf-8')
        except UnicodeError:
            return ua


    def to_database (self):
        """ Write IPs of most blatant offenders to database.

        In get_ip_info_for we collect information from many services
        which may be slow or down, so we run in an extra thread to
        avoid delaying the reset thread.

        """

        with self.dblock:  # make sure we don't reenter if we take too long
            try:
                blocked_sessions = [s for s in self.cache.values ()
                                    if s is not None and s['blocked'] == 2]
                self.get_ipinfo_for (blocked_sessions)

                cursor = cherrypy.engine.pool.connect ().cursor ()
                cursor.execute ('set transaction isolation level serializable')

                for ipsession in blocked_sessions:
                    try:
                        ips = ipsession.ips
                        info = ips.ipinfo

                        expire_days = ipsession['expire_days']
                        if info.is_blackhat ():
                            if info.is_dialup ():
                                # at least 2 days
                                expire_days = max (2, expire_days)
                            else:
                                # at least 7 days
                                expire_days = max (7, expire_days)

                        params = {
                            'ip':          to_cidr (ips.get_ip_to_block ()),
                            'client_ip':   to_cidr (ips.client_ip),
                            'proxy_ip':    to_cidr (ips.proxy_ip),
                            'proxy_type':  ips.proxy_type,
                            'host':        info.hostname,
                            'expires':     (datetime.datetime.now () +
                                            datetime.timedelta (days = expire_days)),
                            'types':       ipsession.get_tags (),
                            'whois':       ' - '.join (filter (None, info.whois.values ())),
                            'user_agents': sorted ([self.ua_decode (ua)
                                                    for ua in ipsession['user_agents']]),
                            'requests':    list (ipsession['requests']),
                            'headers':     [self.ua_decode (h) for h in ipsession['headers']],
                            'count':       1,
                            'hits':        ipsession['hits'],
                            'country':     None,
                            'org':         None,
                            'cidr':        None,
                            'asn':         None,
                            }
                        params.update (info.whois)

                        cursor.execute ('begin')
                        query = """select count, hits from robots.blocks
                                   where ip = %(ip)s and not is_whitelisted"""
                        cursor.execute (query, params)
                        rows = cursor.fetchall ()
                        if len (rows) > 0:
                            count = rows[0][0]
                            hits = rows[0][1]
                            params['count'] = count + 1
                            params['hits']  = hits + ipsession['hits']
                            params['expires'] = (
                                datetime.datetime.now () +
                                datetime.timedelta (
                                    days = expire_days * (2 ** min (count, 10))))
                            query = """update robots.blocks set
                                       count = %(count)s,
                                       expires = %(expires)s,
                                       types = %(types)s,
                                       user_agents = %(user_agents)s,
                                       requests = %(requests)s,
                                       headers = %(headers)s,
                                       hits = %(hits)s
                                       where ip = %(ip)s"""
                        else:
                            query = """insert into robots.blocks
                                       (ip, client_ip, proxy_ip, proxy_type,
                                        host, expires, types, country, org, cidr, asn,
                                        whois, user_agents, requests, headers, hits)
                                       values
                                       (%(ip)s, %(client_ip)s, %(proxy_ip)s, %(proxy_type)s,
                                        %(host)s, %(expires)s, %(types)s,
                                        %(country)s, %(org)s, %(cidr)s, %(asn)s,
                                        %(whois)s, %(user_agents)s, %(requests)s,
                                        %(headers)s, %(hits)s)"""
                        cursor.execute (query, params)
                        cursor.execute ('commit')
                        ipsession['blocked'] = 9
                        # keep on stats page for 5 minutes
                        ipsession.set_expiration (5 * 60)
                        cherrypy.log ("BLOCKED: %s\n" % cursor.mogrify (query, params),
                                      context = 'RATELIMITER', severity = logging.INFO)
                    except DatabaseError as what:
                        cherrypy.log ("SQL Error: %s\n" % what,
                                      context = 'RATELIMITER', severity = logging.ERROR)
                        cherrypy.log ("Query was: %s\n" % cursor.mogrify (query, params),
                                      context = 'RATELIMITER', severity = logging.ERROR)
                        cursor.execute ('rollback')
                    except Exception as what:
                        cherrypy.log ("Error in to_database (): %s" % what,
                                      context = 'RATELIMITER', severity = logging.ERROR)
                        cursor.execute ('rollback')

                cherrypy.log ('Run to_database ()',
                              context = 'RATELIMITER', severity = logging.INFO)

            except Exception as what:
                # make sure background thread never stops
                cherrypy.log ("Error in to_database (): %s" % what,
                              context = 'RATELIMITER', severity = logging.ERROR)


class BlockPage (Page.Page):
    """ Block IP. """

    def index (self, **kwargs): # pylint: disable=R0201
        """ Block IP. """

        if cherrypy.tools.rate_limiter.block (kwargs['ip']):  # pylint: disable=E1101
            return "<p>blocked</p>"
        return "<p>not found</p>"



class UnblockPage (Page.Page):
    """ Unblock IP. """

    def index (self, **kwargs): # pylint: disable=R0201
        """ Unblock IP. """

        if cherrypy.tools.rate_limiter.unblock (kwargs['ip']):  # pylint: disable=E1101
            return "<p>unblocked</p>"
        return "<p>not found</p>"



class TracebackPage (Page.Page):
    """ Produce a traceback in the logs. """

    def index (self, **dummy_kwargs): # pylint: disable=R0201
        """ Traceback. """

        raise Exception



class RateLimiterResetPlugin (cherrypy.process.plugins.Monitor):
    """ Plugin to start the counter reset thread.

    We cannot start any threads before daemonizing,
    so we must start the timer thread by this plugin.

    """

    def __init__ (self, bus):
        # frequency of reset () calls in seconds
        frequency = cherrypy.config.get ('tools.rate_limiter.frequency', 60)
        # pylint: disable=E1101
        super (RateLimiterResetPlugin, self).__init__ (
            bus, cherrypy.tools.rate_limiter.reset, frequency)
        self.name = 'rate_limiter_reset'


class RateLimiterDatabasePlugin (cherrypy.process.plugins.Monitor):
    """ Plugin to start the database writer thread.

    We cannot start any threads before daemonizing,
    so we must start the timer thread by this plugin.

    """

    def __init__ (self, bus):
        # frequency of database calls in seconds
        frequency = cherrypy.config.get ('tools.rate_limiter_database.frequency', 60)
        # pylint: disable=E1101
        super (RateLimiterDatabasePlugin, self).__init__ (
            bus, cherrypy.tools.rate_limiter.to_database, frequency)
        self.name = 'rate_limiter_database'


cherrypy.process.plugins.RateLimiterReset    = RateLimiterResetPlugin
cherrypy.process.plugins.RateLimiterDatabase = RateLimiterDatabasePlugin
