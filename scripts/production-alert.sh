#!/usr/bin/env bash
# Host-level resource alerts for production VPS monitoring (cron hourly).
set -euo pipefail

DISK_THRESHOLD="${DISK_THRESHOLD:-85}"
MEM_THRESHOLD="${MEM_THRESHOLD:-90}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/gym-postgres/daily}"

fail=0

disk_used="$(df / | tail -1 | awk '{print $5}' | tr -d '%')"
if [ "${disk_used}" -ge "${DISK_THRESHOLD}" ]; then
    echo "ALERT: disk usage ${disk_used}% exceeds ${DISK_THRESHOLD}%" >&2
    fail=1
fi

mem_available_pct="$(free | awk '/Mem:/ {printf "%.0f", ($7/$2)*100}')"
if [ "${mem_available_pct}" -lt "$((100 - MEM_THRESHOLD))" ]; then
    echo "ALERT: available memory ${mem_available_pct}% below threshold" >&2
    fail=1
fi

if [ -d "${BACKUP_DIR}" ]; then
    latest="$(find "${BACKUP_DIR}" -name 'gym_*.dump' -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
    if [ -z "${latest}" ]; then
        echo "ALERT: no backup files found in ${BACKUP_DIR}" >&2
        fail=1
    else
        age_hours=$(( ( $(date +%s) - $(stat -c %Y "${latest}") ) / 3600 ))
        if [ "${age_hours}" -gt "${BACKUP_MAX_AGE_HOURS}" ]; then
            echo "ALERT: latest backup is ${age_hours}h old (max ${BACKUP_MAX_AGE_HOURS}h): ${latest}" >&2
            fail=1
        fi
    fi
else
    echo "ALERT: backup directory missing: ${BACKUP_DIR}" >&2
    fail=1
fi

exit "${fail}"
