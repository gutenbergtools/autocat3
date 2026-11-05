# wsgi app for gunicorn

import sys

import cherrypy
from cherrypy.process.plugins import SignalHandler

from CherryPyApp import configure, get_app


configure()

# Disable the autoreload which won't play well
cherrypy.config.update({'engine.autoreload.on': False})

# write logs to WSGI logger
cherrypy.log.wsgi = True

# let's not start the CherryPy HTTP server
cherrypy.server.unsubscribe()

# use a CherryPy signal handler with some tweaks
def exit_on_term():
    """On SIGTERM, shut down the bus and then exit the process."""
    cherrypy.engine.exit()
    sys.exit(0)


signalhandler = SignalHandler(cherrypy.engine)
signalhandler.handlers['SIGTERM'] = exit_on_term
signalhandler.subscribe()

# Run the engine but don't block on it
cherrypy.engine.start()

app = get_app()
