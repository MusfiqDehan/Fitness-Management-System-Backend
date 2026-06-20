#!/usr/bin/env sh
# Run Django migrations against PostgreSQL directly (bypasses PgBouncer).
set -e

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

# --no-deps: only needs PostgreSQL, not PgBouncer/backend/redis.
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps \
  -e RUN_MIGRATIONS=1 \
  -e USE_PGBOUNCER=0 \
  backend python manage.py migrate_schemas --noinput "$@"
