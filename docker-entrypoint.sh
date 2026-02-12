#!/bin/bash

# Script d'entrée pour Docker
# Attend que MySQL soit prêt et exécute les migrations

set -e

echo "Attente de la disponibilité de MySQL..."

# Attendre que MySQL soit disponible
while ! nc -z mysql 3306; do
  echo "MySQL n'est pas encore disponible - attente..."
  sleep 2
done

echo "MySQL est disponible - exécution des migrations"

# Exécuter les migrations
python manage.py migrate --noinput

# Créer un superutilisateur si nécessaire (optionnel)
# python manage.py createsuperuser --noinput || true

echo "Démarrage de l'application Django..."

# Exécuter la commande passée en argument
exec "$@"

