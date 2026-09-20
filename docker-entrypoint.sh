#!/bin/bash
set -euo pipefail

# Les migrations sont versionnées et livrées dans l'image : on ne les régénère
# JAMAIS au démarrage. Un `makemigrations` ici recréerait un 0001_initial que
# `migrate` croirait déjà appliqué (django_migrations ne stocke aucun hash de
# contenu), et le schéma divergerait silencieusement d'une base à l'autre.
echo "Contrôle de l'historique des migrations..."
python manage.py check_migration_baseline

echo "Application des migrations..."
python manage.py migrate --noinput

echo "Compilation des traductions (locale/*/LC_MESSAGES/*.po -> .mo)..."
python manage.py translations compile

echo "Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

echo "Démarrage de Gunicorn..."
exec "$@"
