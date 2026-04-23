#!/bin/sh
set -e

echo "Waiting for PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT..."

while ! nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
  sleep 1
done

echo "PostgreSQL is up"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn flashcards_project.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --timeout 120