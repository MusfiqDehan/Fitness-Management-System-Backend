#!/bin/sh
# Production ADMS launcher — isolated Gunicorn pool for biometric device traffic.
set -e

export GUNICORN_BIND="${ADMS_BIND:-0.0.0.0:8022}"
export GUNICORN_WORKERS="${ADMS_WORKERS:-4}"
export GUNICORN_THREADS="${ADMS_THREADS:-4}"
export GUNICORN_TIMEOUT="${ADMS_TIMEOUT:-90}"

exec gunicorn config.wsgi:application -c /app/gunicorn.conf.py
