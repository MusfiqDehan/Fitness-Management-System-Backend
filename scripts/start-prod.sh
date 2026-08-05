#!/usr/bin/env bash
# Start production stack in the correct order after a server reboot.
# Traefik must be up first (creates traefik_proxy network), then backend, then frontend.
#
# Usage:
#   ./scripts/start-prod.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAEFIK_DIR="${TRAEFIK_DIR:-/srv/shared/traefik}"
FRONTEND_DIR="${FRONTEND_DIR:-/srv/fullstacks/Fitness-Management-System/frontend}"

echo "==> Starting Traefik..."
docker compose --env-file "${TRAEFIK_DIR}/.env" \
  -f "${TRAEFIK_DIR}/docker-compose.traefik.yml" up -d

echo "==> Starting backend infrastructure and app services..."
cd "$ROOT_DIR"
docker compose -f docker-compose.prod.yml up -d db redis pgbouncer
docker compose -f docker-compose.prod.yml up -d --wait --wait-timeout 120 db redis pgbouncer
docker compose -f docker-compose.prod.yml up -d backend backend_ws backend_adms celery_worker celery_beat autoheal

echo "==> Starting frontend..."
docker compose -f "${FRONTEND_DIR}/docker-compose.prod.yml" up -d frontend

echo "==> Waiting for backend health..."
deadline=$((SECONDS + 120))
until docker compose -f docker-compose.prod.yml ps backend | grep -q healthy; do
  if (( SECONDS >= deadline )); then
    echo "[FAIL] Backend did not become healthy in time" >&2
    docker compose -f docker-compose.prod.yml ps
    exit 1
  fi
  sleep 3
done

echo "==> Production stack is up."
curl -fsS "https://fitness.musfiqdehan.com/api/v1/health/live/" >/dev/null && echo "[OK] Public API is reachable."
