#!/bin/bash
set -e

echo "Attente de la disponibilité de MySQL..."

until mysqladmin ping -h"$MYSQL_HOST" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent; do
  echo "MySQL n'est pas encore disponible - attente..."
  sleep 2
done

echo "MySQL est disponible - exécution des migrations"

python manage.py migrate --noinput

echo "Démarrage de l'application Django..."

exec "$@"
