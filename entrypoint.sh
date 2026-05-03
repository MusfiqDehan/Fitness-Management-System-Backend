#!/bin/sh
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

# Collect static files only in production (DEBUG=False)
if [ "${DEBUG}" != "true" ] && [ "${DEBUG}" != "True" ]; then
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
fi

echo "Starting server..."
exec "$@"
