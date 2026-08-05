# Production backup and restore

## Backup (daily)

From the backend directory on the VPS host:

```bash
export POSTGRES_USER=gym_user
export POSTGRES_DB=gym_db
export PGHOST=localhost
export PGPORT=5432
export BACKUP_DIR=/var/backups/gym-postgres
./scripts/backup-postgres.sh
```

Recommended cron (02:30 UTC daily):

```cron
30 2 * * * cd /path/to/gym_app_new_backend && POSTGRES_USER=gym_user POSTGRES_DB=gym_db PGHOST=localhost PGPORT=5432 ./scripts/backup-postgres.sh >> /var/log/gym-backup.log 2>&1
```

Retention: 7 daily + 4 weekly copies (configured in the script).

## Restore

1. Stop application containers (keep Traefik if needed for maintenance page):

   ```bash
   docker compose -f docker-compose.prod.yml stop backend celery_worker celery_beat
   ```

2. Restore into PostgreSQL (uses direct `db` connection, not PgBouncer):

   ```bash
   pg_restore -h localhost -p 5432 -U gym_user -d gym_db --clean --if-exists /var/backups/gym-postgres/daily/gym_YYYYMMDD_HHMMSS.dump
   ```

3. Run migrations if needed (direct PostgreSQL, not PgBouncer):

   ```bash
   ./scripts/migrate-prod.sh
   ```

   Or manually (must rebuild backend image first so entrypoint is current):

   ```bash
   docker compose -f docker-compose.prod.yml build backend
   docker compose -f docker-compose.prod.yml run --rm --no-deps \
     -e RUN_MIGRATIONS=1 \
     backend python manage.py migrate_schemas --noinput
   ```

4. Start stack:

   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

5. Smoke test:

   ```bash
   curl -fsS https://fitness.musfiqdehan.com/api/v1/health/ready/
   curl -fsS http://tenant.fitness.musfiqdehan.com/iclock/cdata?SN=YOUR_DEVICE_SN
   ```

## Production triage quick reference

| Symptom | Check |
|---------|-------|
| Slow API | `docker stats`, Redis `INFO memory`, PgBouncer pool stats |
| DB connections exhausted | `SELECT count(*) FROM pg_stat_activity;` via `docker exec gym-db psql` |
| ADMS offline | HTTP (not HTTPS) device URL, Traefik `backend-adms` router, device `SN` param |
| Disk full | `df -h`, backup retention, Docker log rotation |
| Celery backlog | `docker exec gym-celery-worker celery -A config.celery:app inspect active` |

## Load test acceptance (10k DAU readiness)

- Sustain **100 req/s** for 5 minutes against cached HTTPS read endpoints
- **p95 latency < 500 ms** on cached reads
- **Zero HTTP 5xx** during test window
- Concurrent HTTP ADMS heartbeats must not receive HTTP 429

Example with k6:

```bash
k6 run --vus 50 --duration 5m scripts/load-test-read-endpoints.js
```
