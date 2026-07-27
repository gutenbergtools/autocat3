import multiprocessing

wsgi_app = "wsgi:app"
bind = "0.0.0.0:8000"
worker_class = "gthread"

# total autocat workers (threads * workers) * 3 must be < maximum number of
# postgres connections. libgutenberg is not efficient on how it manages
# pooled database connections and requests often require up to 3 connections
autocat_max_workers = 96
workers = multiprocessing.cpu_count()

# Don't run fewer than 1 thread, or more than 32. More than 32 results in
# GIL contention based on benchmarking.
threads = min(max(autocat_max_workers // workers, 1), 32)

# limit the total number of connections
backlog = 512
worker_connections = 1000

# where to write access and error logs
accesslog = "/var/lib/autocat/log/access.log"
errorlog = "/var/lib/autocat/log/error.log"

try:
    from local_gunicorn import *
except ImportError:
    pass
