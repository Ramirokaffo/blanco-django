#!/bin/bash
set -e

echo "Exécution des migrations..."

python manage.py migrate --noinput

exec "$@"
