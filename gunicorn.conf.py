"""Gunicorn configuration for production HTTP workers."""

import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8021")
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True


def post_fork(_server, _worker):
    # Avoid stale PostgreSQL connections inherited across worker forks.
    from django.db import connections

    connections.close_all()
