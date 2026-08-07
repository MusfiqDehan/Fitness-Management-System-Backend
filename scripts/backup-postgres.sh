#!/usr/bin/env bash
# Daily PostgreSQL backup with retention: 7 daily + 4 weekly.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/gym-postgres}"
RETENTION_DAILY="${RETENTION_DAILY:-7}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-4}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DAY_OF_WEEK="$(date +%u)" # 1=Mon … 7=Sun

mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly"

: "${POSTGRES_USER:?POSTGRES_USER required}"
: "${POSTGRES_DB:?POSTGRES_DB required}"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"

DAILY_FILE="${BACKUP_DIR}/daily/gym_${TIMESTAMP}.dump"
pg_dump -Fc -h "${PGHOST}" -p "${PGPORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -f "${DAILY_FILE}"

# Keep one weekly copy on Sundays
if [ "${DAY_OF_WEEK}" = "7" ]; then
    cp "${DAILY_FILE}" "${BACKUP_DIR}/weekly/gym_week_${TIMESTAMP}.dump"
fi

# Prune old daily backups
ls -1t "${BACKUP_DIR}/daily"/gym_*.dump 2>/dev/null | tail -n +"$((RETENTION_DAILY + 1))" | xargs -r rm -f

# Prune old weekly backups
ls -1t "${BACKUP_DIR}/weekly"/gym_week_*.dump 2>/dev/null | tail -n +"$((RETENTION_WEEKLY + 1))" | xargs -r rm -f

echo "Backup complete: ${DAILY_FILE}"
