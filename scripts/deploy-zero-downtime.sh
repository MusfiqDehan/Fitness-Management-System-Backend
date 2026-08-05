#!/usr/bin/env bash
# Zero-downtime production deploy for the gym backend stack.
#
# Usage:
#   ./scripts/deploy-zero-downtime.sh
#
# Environment:
#   SKIP_GIT_PULL=1     Skip git fetch/reset (CI sets this after pulling)
#   SKIP_MIGRATIONS=1   Skip database migrations
#   SKIP_VERIFY=1       Skip post-deploy verification
#   IMAGE_TAG           Image tag (default: short git SHA)
#   COMPOSE_FILE        Compose file (default: docker-compose.prod.yml)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-0}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"

cd "$ROOT_DIR"

export IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
echo "==> Deploying backend image tag: ${IMAGE_TAG}"

if [[ "$SKIP_GIT_PULL" != "1" ]]; then
  echo "==> Pulling latest code from production branch..."
  git fetch origin main
  git reset --hard origin/main
  export IMAGE_TAG="$(git rev-parse --short HEAD)"
  echo "==> Image tag after pull: ${IMAGE_TAG}"
fi

echo "==> Building application images (running containers stay up)..."
docker compose -f "$COMPOSE_FILE" build backend backend_ws backend_adms celery_worker celery_beat

# Retain rollback tag before rolling update.
if docker image inspect "gym-backend:latest" >/dev/null 2>&1; then
  PREVIOUS_TAG="${PREVIOUS_IMAGE_TAG:-}"
  if [[ -z "$PREVIOUS_TAG" ]]; then
    PREVIOUS_TAG="$(docker image inspect gym-backend:latest --format '{{index .RepoTags 0}}' 2>/dev/null | cut -d: -f2 || true)"
  fi
  if [[ -n "$PREVIOUS_TAG" && "$PREVIOUS_TAG" != "$IMAGE_TAG" && "$PREVIOUS_TAG" != "latest" ]]; then
    echo "==> Previous image tag retained for rollback: gym-backend:${PREVIOUS_TAG}"
  fi
fi

docker tag "gym-backend:latest" "gym-backend:${IMAGE_TAG}" 2>/dev/null || true

if [[ "$SKIP_MIGRATIONS" != "1" ]]; then
  echo "==> Running database migrations (old app still serving traffic)..."
  ./scripts/migrate-prod.sh

  echo "==> Syncing feature registry..."
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps backend \
    python manage.py sync_features
fi

ROLLING_SCRIPT="$ROOT_DIR/scripts/rolling-update-service.sh"
chmod +x "$ROLLING_SCRIPT"

echo "==> Rolling update: backend (API)..."
SKIP_BUILD=1 "$ROLLING_SCRIPT" backend

echo "==> Rolling update: backend_adms..."
SKIP_BUILD=1 "$ROLLING_SCRIPT" backend_adms

echo "==> Rolling update: backend_ws..."
SKIP_BUILD=1 "$ROLLING_SCRIPT" backend_ws

echo "==> Rolling update: celery_worker..."
SKIP_BUILD=1 "$ROLLING_SCRIPT" celery_worker

echo "==> Updating celery_beat (single instance, brief scheduler gap acceptable)..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps celery_beat

if [[ "$SKIP_VERIFY" != "1" ]]; then
  echo "==> Running post-deploy verification..."
  ./scripts/post_deploy_verify.sh
fi

echo "==> Pruning unused Docker images..."
docker image prune -f

echo "==> Backend zero-downtime deployment complete (tag: ${IMAGE_TAG})."
