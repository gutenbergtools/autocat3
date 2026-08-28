import multiprocessing

wsgi_app = "wsgi:app"
bind = "0.0.0.0:8000"
worker_class = "gthread"

# total autocat workers (threads * workers) must be < maximum number of
# postgres connections
autocat_max_workers = 100
workers = multiprocessing.cpu_count()
threads = max(autocat_max_workers // workers, 1)

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
