# wsgi app for gunicorn

import cherrypy

from CherryPyApp import configure, get_app


configure()

# Disable the autoreload which won't play well
cherrypy.config.update({'engine.autoreload.on': False})

# write logs to WSGI logger
cherrypy.log.wsgi = True

# let's not start the CherryPy HTTP server
cherrypy.server.unsubscribe()

# use CherryPy's signal handling
cherrypy.engine.signals.subscribe()

# Run the engine but don't block on it
cherrypy.engine.start()

app = get_app()
