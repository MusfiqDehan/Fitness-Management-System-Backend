#!/bin/sh
# Production ADMS launcher — isolated from API/WebSocket workers.
set -e

WORKERS="${ADMS_ASGI_WORKERS:-2}"
BIND="${ADMS_ASGI_BIND:-0.0.0.0:8022}"

if command -v hypercorn >/dev/null 2>&1; then
    exec hypercorn config.asgi_http:application --bind "${BIND}" --workers "${WORKERS}"
fi

echo "hypercorn not found; falling back to single daphne process" >&2
exec daphne -b 0.0.0.0 -p 8022 config.asgi_http:application
