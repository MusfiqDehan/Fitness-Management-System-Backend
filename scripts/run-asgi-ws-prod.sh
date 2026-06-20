#!/bin/sh
# Production WebSocket launcher — daphne handles many concurrent /ws connections.
set -e

PORT="${WS_PORT:-8023}"

exec daphne -b 0.0.0.0 -p "${PORT}" config.asgi_ws:application
