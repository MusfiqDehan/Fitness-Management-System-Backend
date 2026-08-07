#!/bin/sh
# Production API launcher — Gunicorn gthread workers for stable Django REST traffic.
set -e

export GUNICORN_BIND="${API_BIND:-0.0.0.0:8021}"
export GUNICORN_WORKERS="${API_WORKERS:-4}"
export GUNICORN_THREADS="${API_THREADS:-2}"
export GUNICORN_TIMEOUT="${API_TIMEOUT:-120}"

exec gunicorn config.wsgi:application -c /app/gunicorn.conf.py
