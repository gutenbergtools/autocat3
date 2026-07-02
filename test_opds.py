"""
test_opds.py — HTTP load test for the OPDS 2 feed.

Starts an in-process CherryPy server with production pool/thread limits,
warms routes, then runs REQUESTS_PER_ROUTE GETs per route at CLIENT_CONCURRENCY
(defaults: 100/20, matching CherryPy.conf).

LOAD_MODE:
  mixed      — all routes interleaved in one concurrent run
  per_route  — one route at a time

Run: python3 test_opds.py [mixed|per_route]
"""

import os
import socket
import sys
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

REQUESTS_PER_ROUTE = 100
CLIENT_CONCURRENCY = 20
WARMUP_REQUESTS = 5
LOAD_MODE = "mixed"  # mixed | per_route

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
    ("/opds/bookshelves?category=LITERATURE", "bookshelf category nav"),
    ("/opds/bookshelf_groups?category=LITERATURE", "bookshelf category groups"),
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


def warmup_routes(base_url, routes):
    for path, _label in routes:
        for _ in range(WARMUP_REQUESTS):
            response = http_get(base_url, path)
            if response.status_code != 200:
                raise RuntimeError(f"Warmup failed for {path}: HTTP {response.status_code}")


def percentile_ms(samples, p):
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * p) - 1))
    return ordered[idx]


def summarize(samples, error_count, request_count, elapsed_s):
    count = len(samples)
    rps = count / elapsed_s if elapsed_s > 0 else 0.0
    err_pct = 100.0 * error_count / request_count if request_count else 0.0
    p50_ms = percentile_ms(samples, 0.50) if samples else 0.0
    p95_ms = percentile_ms(samples, 0.95) if samples else 0.0
    p99_ms = percentile_ms(samples, 0.99) if samples else 0.0
    status = "OK" if error_count == 0 else "ERR"
    return count, err_pct, rps, p50_ms, p95_ms, p99_ms, status


def execute_load(base_url, jobs, client_concurrency):
    samples_by_label = {}
    errors_by_label = {}

    def one_request(path, label):
        try:
            start = time.perf_counter()
            response = http_get(base_url, path)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            return label, (time.perf_counter() - start) * 1000, None
        except Exception as exc:
            return label, None, str(exc)

    batch_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=client_concurrency) as pool:
        futures = [pool.submit(one_request, path, label) for path, label in jobs]
        for future in as_completed(futures):
            label, ms, err = future.result()
            if err:
                errors_by_label.setdefault(label, []).append(err)
            else:
                samples_by_label.setdefault(label, []).append(ms)
    elapsed_s = time.perf_counter() - batch_start
    return samples_by_label, errors_by_label, elapsed_s


def interleaved_jobs(routes, requests_per_route):
    n = len(routes)
    return [routes[i % n] for i in range(n * requests_per_route)]


def print_report(title, labels, samples_by_label, errors_by_label, elapsed_s, per_route_count, total_jobs=None, elapsed_by_label=None):
    width = 105
    job_count = total_jobs or per_route_count * len(labels)
    print("=" * width)
    print(f"OPDS load test — {title} ({job_count} requests, concurrency {CLIENT_CONCURRENCY})")
    print("=" * width)
    print(
        f"{'Route':<22} | {'Reqs':>5} | {'Err%':>5} | {'RPS':>6} | "
        f"{'P50 ms':>7} | {'P95 ms':>7} | {'P99 ms':>7} | Status"
    )
    print("=" * width)
    all_samples, total_errors = [], 0
    for label in labels:
        samples = samples_by_label.get(label, [])
        errors = errors_by_label.get(label, [])
        total_errors += len(errors)
        all_samples.extend(samples)
        route_elapsed = (elapsed_by_label or {}).get(label, elapsed_s)
        stats = summarize(samples, len(errors), per_route_count, route_elapsed)
        count, err_pct, rps, p50, p95, p99, status = stats
        print(
            f"{label:<22} | {count:>5} | {err_pct:>5.1f} | {rps:>6.1f} | "
            f"{p50:>7.1f} | {p95:>7.1f} | {p99:>7.1f} | {status}"
        )
    if total_jobs:
        stats = summarize(all_samples, total_errors, total_jobs, elapsed_s)
        count, err_pct, rps, p50, p95, p99, status = stats
        print("-" * width)
        print(
            f"{'TOTAL':<22} | {count:>5} | {err_pct:>5.1f} | {rps:>6.1f} | "
            f"{p50:>7.1f} | {p95:>7.1f} | {p99:>7.1f} | {status}"
        )
    print("=" * width)


def run_mixed(base_url):
    warmup_routes(base_url, LOAD_ROUTES)
    jobs = interleaved_jobs(LOAD_ROUTES, REQUESTS_PER_ROUTE)
    samples, errors, elapsed = execute_load(base_url, jobs, CLIENT_CONCURRENCY)
    labels = [label for _path, label in LOAD_ROUTES]
    print_report("mixed load", labels, samples, errors, elapsed, REQUESTS_PER_ROUTE, len(jobs))


def run_per_route(base_url):
    labels, samples, errors, elapsed_by_label = [], {}, {}, {}
    for path, label in LOAD_ROUTES:
        warmup_routes(base_url, ((path, label),))
        route_samples, route_errors, elapsed = execute_load(
            base_url, [(path, label)] * REQUESTS_PER_ROUTE, CLIENT_CONCURRENCY
        )
        labels.append(label)
        samples[label] = route_samples.get(label, [])
        errors[label] = route_errors.get(label, [])
        elapsed_by_label[label] = elapsed
    print_report(
        "per-route load", labels, samples, errors, 0.0, REQUESTS_PER_ROUTE,
        elapsed_by_label=elapsed_by_label,
    )


def run_load(mode=LOAD_MODE):
    if mode not in ("mixed", "per_route"):
        raise SystemExit(f"Unknown LOAD_MODE {mode!r}; use mixed or per_route")
    with opds_test_server() as base_url:
        if mode == "mixed":
            run_mixed(base_url)
        else:
            run_per_route(base_url)


if __name__ == "__main__":
    run_load(sys.argv[1] if len(sys.argv) > 1 else LOAD_MODE)
