#!/bin/sh
# Production ASGI launcher — multiple workers for concurrent HTTP + WebSocket.
set -e

WORKERS="${ASGI_WORKERS:-2}"
BIND="${ASGI_BIND:-0.0.0.0:8021}"

if command -v hypercorn >/dev/null 2>&1; then
    exec hypercorn config.asgi:application --bind "${BIND}" --workers "${WORKERS}"
fi

echo "hypercorn not found; falling back to single daphne process" >&2
exec daphne -b 0.0.0.0 -p 8021 config.asgi:application
