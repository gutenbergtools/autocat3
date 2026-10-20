import multiprocessing

wsgi_app = "wsgi:app"
bind = "0.0.0.0:8000"

# See https://gunicorn.org/design/ for info on worker_class / workers / threads
worker_class = "gthread"

# total autocat workers (threads * workers) * 5 must be < maximum number of
# postgres connections, leaving some spare connections for other users.
# libgutenberg is not efficient on how it manages pooled database connections
# and bibreq pages often require up to 5 connections

# 300 max connections, 2 autocat3 instances (dev & prod), 50 extra connections
postgres_max_connections = (300 - 50) // 2
total_max_workers = postgres_max_connections // 5

# use all available CPUs
workers = min(total_max_workers, multiprocessing.cpu_count())

# Don't run fewer than 1 thread, or more than 32. More than 32 results in
# GIL contention based on benchmarking.
threads = min(max(total_max_workers // workers, 1), 32)

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
