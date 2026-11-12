"""WSGI entry point: gunicorn wsgi:application   (or uWSGI / mod_wsgi)."""
from paidwalk import create_app

application = create_app()
