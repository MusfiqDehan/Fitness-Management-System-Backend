#!/bin/sh
# Backwards-compatible alias for the API-only launcher.
set -e
exec /bin/sh /app/scripts/run-asgi-api-prod.sh
