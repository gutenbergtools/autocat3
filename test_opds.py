"""
test_opds.py — HTTP load test for the OPDS 2 feed.

Starts an in-process CherryPy server with production pool/thread limits,
warms each route, then times REQUESTS_PER_ROUTE GETs using CLIENT_CONCURRENCY
parallel client threads (defaults: 20/20, matching CherryPy.conf).

Run: python3 test_opds.py
"""

import os
import socket
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

import cherrypy
import requests
from cherrypy.process import plugins
from libgutenberg import GutenbergDatabase

import ConnectionPool  # noqa: F401  registers plugins.ConnectionPool
from OPDS2 import OPDSFeed, OPDS_MOUNT_CONFIG

ROOT = os.path.dirname(os.path.abspath(__file__))
TEST_CONF = os.path.join(ROOT, "test.conf")

# CherryPy.conf production server/DB pool limits.
PROD_THREAD_POOL = 20
PROD_POOL_SIZE = 20
PROD_MAX_OVERFLOW = 0
PROD_POOL_TIMEOUT = 3

REQUESTS_PER_ROUTE = 1000
CLIENT_CONCURRENCY = 20
WARMUP_REQUESTS = 2

SERVER_TUNING = {
    "server.thread_pool": PROD_THREAD_POOL,
    "server.thread_pool_max": PROD_THREAD_POOL,
    "server.socket_queue_size": 10,
    "sqlalchemy.pool_size": PROD_POOL_SIZE,
    "sqlalchemy.max_overflow": PROD_MAX_OVERFLOW,
    "sqlalchemy.timeout": PROD_POOL_TIMEOUT,
    "sqlalchemy.recycle": 3600,
}

LOAD_ROUTES = (
    ("/opds/", "index"),
    ("/opds/search?query=Shakespeare", "search"),
    ("/opds/search?query=Shakespeare&page=2", "search page 2"),
    ("/opds/publications?id=1342", "publication"),
    ("/opds/also?id=1342", "also downloaded"),
    ("/opds/bookshelves", "bookshelves index"),
    ("/opds/bookshelves?category=LITERATURE", "bookshelf category"),
    ("/opds/bookshelves?id=68", "bookshelf id"),
    ("/opds/subjects?id=1", "subject browse"),
    ("/opds/loccs?parent=P", "locc nav P"),
    ("/opds/loccs?parent=PN", "locc leaf PN"),
    ("/opds/loccs", "loccs index"),
)


def get_ephemeral_port(host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


@contextmanager
def opds_test_server(host="127.0.0.1"):
    cherrypy.config.update(TEST_CONF)
    cherrypy.config.update(SERVER_TUNING)
    port = get_ephemeral_port(host)
    cherrypy.config.update(
        {
            "server.socket_host": host,
            "server.socket_port": port,
            "engine.autoreload.on": False,
            "engine.SOCKET_TIMEOUT": 60,
            "log.screen": False,
        }
    )
    GutenbergDatabase.options.update(cherrypy.config)
    cherrypy.engine.pool = plugins.ConnectionPool(
        cherrypy.engine,
        params=GutenbergDatabase.get_connection_params(cherrypy.config),
    )
    cherrypy.engine.pool.subscribe()
    cherrypy.tree.mount(OPDSFeed(), "/opds", OPDS_MOUNT_CONFIG)
    cherrypy.engine.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        cherrypy.engine.exit()


def http_get(base_url, path, timeout=60):
    return requests.get(f"{base_url}{path}", timeout=timeout)


def warmup_route(base_url, path):
    """Prime caches and DB plans before timed requests."""
    for _ in range(WARMUP_REQUESTS):
        response = http_get(base_url, path)
        if response.status_code != 200:
            raise RuntimeError(f"Warmup failed for {path}: HTTP {response.status_code}")


def benchmark_route(base_url, path, request_count, client_concurrency):
    samples = []
    errors = []

    def one_request():
        start = time.perf_counter()
        response = http_get(base_url, path)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return (time.perf_counter() - start) * 1000

    with ThreadPoolExecutor(max_workers=client_concurrency) as pool:
        futures = [pool.submit(one_request) for _ in range(request_count)]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except Exception as exc:
                errors.append(str(exc))

    avg_ms = statistics.mean(samples) if samples else 0.0
    if samples:
        ordered = sorted(samples)
        p95_ms = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    else:
        p95_ms = 0.0
    status = "OK" if not errors else errors[0]
    return len(samples), avg_ms, p95_ms, status


def run_load():
    with opds_test_server() as base_url:
        print("=" * 90)
        print(f"{'Route':<22} | {'Reqs':>5} | {'Avg ms':>8} | {'P95 ms':>8} | Status")
        print("=" * 90)
        for path, label in LOAD_ROUTES:
            warmup_route(base_url, path)
            count, avg_ms, p95_ms, status = benchmark_route(
                base_url,
                path,
                REQUESTS_PER_ROUTE,
                CLIENT_CONCURRENCY,
            )
            print(
                f"{label:<22} | {count:>5} | {avg_ms:>8.1f} | {p95_ms:>8.1f} | {status}"
            )
        print("=" * 90)


if __name__ == "__main__":
    run_load()
