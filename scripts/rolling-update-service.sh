#!/usr/bin/env bash
# Rolling update a single Docker Compose service with zero downtime.
# Scales to 2 replicas, waits for the new container to be healthy, stops the old
# one gracefully, then normalizes back to 1 replica.
#
# Usage:
#   ./scripts/rolling-update-service.sh <service>
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/rolling-update-service.sh backend
#
# Environment:
#   COMPOSE_FILE       Compose file (default: docker-compose.prod.yml)
#   STOP_TIMEOUT       Seconds to wait for graceful stop (default: 35)
#   HEALTH_TIMEOUT     Seconds to wait for new container health (default: 180)
#   SKIP_BUILD         Set to 1 to skip image build for this service

set -euo pipefail

SERVICE="${1:-}"
if [[ -z "$SERVICE" ]]; then
  echo "Usage: $0 <service>" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
STOP_TIMEOUT="${STOP_TIMEOUT:-35}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
SKIP_BUILD="${SKIP_BUILD:-0}"

cd "$ROOT_DIR"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

container_health_status() {
  local container_id="$1"
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || echo "missing"
}

container_created_at() {
  local container_id="$1"
  docker inspect --format '{{.Created}}' "$container_id"
}

wait_for_healthy() {
  local container_id="$1"
  local deadline=$((SECONDS + HEALTH_TIMEOUT))

  while (( SECONDS < deadline )); do
    local status
    status="$(container_health_status "$container_id")"
    case "$status" in
      healthy)
        return 0
        ;;
      unhealthy)
        echo "[FAIL] Container ${container_id:0:12} reported unhealthy" >&2
        docker logs --tail 50 "$container_id" >&2 || true
        return 1
        ;;
      none)
        # Service without a healthcheck — treat running state as ready.
        if docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null | grep -q true; then
          return 0
        fi
        ;;
    esac
    sleep 2
  done

  echo "[FAIL] Timed out waiting for container ${container_id:0:12} to become healthy" >&2
  return 1
}

pick_oldest_container() {
  local ids=("$@")
  local oldest_id=""
  local oldest_created=""

  for id in "${ids[@]}"; do
    [[ -z "$id" ]] && continue
    local created
    created="$(container_created_at "$id")"
    if [[ -z "$oldest_created" || "$created" < "$oldest_created" ]]; then
      oldest_created="$created"
      oldest_id="$id"
    fi
  done

  echo "$oldest_id"
}

pick_newest_container() {
  local ids=("$@")
  local newest_id=""
  local newest_created=""

  for id in "${ids[@]}"; do
    [[ -z "$id" ]] && continue
    local created
    created="$(container_created_at "$id")"
    if [[ -z "$newest_created" || "$created" > "$newest_created" ]]; then
      newest_created="$created"
      newest_id="$id"
    fi
  done

  echo "$newest_id"
}

mapfile -t IDS_BEFORE < <(compose ps -q "$SERVICE" 2>/dev/null || true)

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "==> Building ${SERVICE}..."
  compose build "$SERVICE"
fi

if [[ ${#IDS_BEFORE[@]} -eq 0 || -z "${IDS_BEFORE[0]:-}" ]]; then
  echo "==> No existing ${SERVICE} container — starting fresh..."
  compose up -d --no-deps "$SERVICE"
  mapfile -t IDS_AFTER < <(compose ps -q "$SERVICE")
  if [[ ${#IDS_AFTER[@]} -eq 0 ]]; then
    echo "[FAIL] ${SERVICE} did not start" >&2
    exit 1
  fi
  wait_for_healthy "${IDS_AFTER[0]}"
  echo "==> ${SERVICE} is up and healthy."
  exit 0
fi

echo "==> Scaling ${SERVICE} to 2 (rolling update)..."
compose up -d --no-deps --scale "${SERVICE}=2" --no-recreate "$SERVICE"

mapfile -t IDS_AFTER < <(compose ps -q "$SERVICE")
if [[ ${#IDS_AFTER[@]} -lt 2 ]]; then
  echo "[FAIL] Expected 2 ${SERVICE} containers, found ${#IDS_AFTER[@]}" >&2
  compose ps "$SERVICE" >&2 || true
  exit 1
fi

NEW_ID="$(pick_newest_container "${IDS_AFTER[@]}")"
OLD_ID="$(pick_oldest_container "${IDS_AFTER[@]}")"

if [[ "$NEW_ID" == "$OLD_ID" ]]; then
  echo "[FAIL] Could not distinguish old and new ${SERVICE} containers" >&2
  exit 1
fi

echo "==> Waiting for new ${SERVICE} container (${NEW_ID:0:12}) to be healthy..."
wait_for_healthy "$NEW_ID"

echo "==> Stopping old ${SERVICE} container (${OLD_ID:0:12}) gracefully..."
docker stop -t "$STOP_TIMEOUT" "$OLD_ID"
docker rm "$OLD_ID"

echo "==> Normalizing ${SERVICE} back to 1 replica..."
compose up -d --no-deps --scale "${SERVICE}=1" --no-recreate "$SERVICE"

mapfile -t IDS_FINAL < <(compose ps -q "$SERVICE")
if [[ ${#IDS_FINAL[@]} -ne 1 ]]; then
  echo "[WARN] Expected 1 ${SERVICE} container after normalize, found ${#IDS_FINAL[@]}"
fi

echo "==> Rolling update complete for ${SERVICE}."
