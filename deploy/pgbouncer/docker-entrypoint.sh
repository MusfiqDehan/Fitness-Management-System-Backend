#!/bin/sh
set -e

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "POSTGRES_USER and POSTGRES_PASSWORD are required for PgBouncer" >&2
    exit 1
fi

printf '"%s" "%s"\n' "${POSTGRES_USER}" "${POSTGRES_PASSWORD}" > /etc/pgbouncer/userlist.txt
exec pgbouncer /etc/pgbouncer/pgbouncer.ini
