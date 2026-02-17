#!/bin/bash
set -e

echo "Attente de MySQL..."

until mysql -h"$MYSQL_HOST" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do
  echo "MySQL pas prêt, attente..."
  sleep 2
done

echo "MySQL prêt ✅"

echo "Exécution des migrations..."
python manage.py migrate --noinput

echo "Démarrage de Gunicorn..."
exec "$@"
