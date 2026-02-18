#!/bin/bash
# set -e

echo "Exécution des migrations..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "Démarrage de Gunicorn..."
exec "$@"
