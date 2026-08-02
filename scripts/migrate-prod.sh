#!/usr/bin/env sh
# Run Django migrations against PostgreSQL directly (bypasses PgBouncer).
set -e

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

run_backend() {
  # --no-deps: only needs PostgreSQL, not PgBouncer/backend/redis.
  docker compose -f "${COMPOSE_FILE}" run --rm --no-deps \
    -e RUN_MIGRATIONS=1 \
    -e USE_PGBOUNCER=0 \
    backend "$@"
}

# Repair SHARED_APPS that have django_migrations rows but missing tables
# (common when an app moves from TENANT_APPS into SHARED_APPS), then migrate.
run_backend python manage.py repair_shared_schema_drift
run_backend python manage.py migrate_schemas --noinput "$@"
