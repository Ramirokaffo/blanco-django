#!/bin/bash
# set -e

# echo "Attente de MySQL..."
# echo "HOST=$MYSQL_HOST USER=$MYSQL_USER DB=$MYSQL_DATABASE"

# until mysql -h"$MYSQL_HOST" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do
#   echo "MySQL pas prêt, attente..."
#   sleep 2
# done

# echo "MySQL prêt ✅"

echo "Exécution des migrations..."
python manage.py migrate --noinput

echo "Démarrage de Gunicorn..."
exec "$@"
