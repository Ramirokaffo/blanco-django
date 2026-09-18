#!/bin/bash
set -euo pipefail

# Les migrations ne sont pas versionnées (voir .gitignore : */migrations/*.py) :
# elles sont régénérées à partir des modèles à chaque démarrage, puis appliquées.
echo "Génération et application des migrations..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput

echo "Compilation des traductions (locale/*/LC_MESSAGES/*.po -> .mo)..."
python manage.py translations compile

echo "Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

echo "Démarrage de Gunicorn..."
exec "$@"
