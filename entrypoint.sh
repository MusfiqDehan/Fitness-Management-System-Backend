#!/bin/sh
set -e

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Ensuring superadmin account exists..."
python manage.py create_superadmin

echo "Starting server..."
exec "$@"
