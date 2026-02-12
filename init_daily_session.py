#!/usr/bin/env python
"""
Script pour initialiser une session Daily pour les tests
"""
import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blanco.settings')
django.setup()

from core.models import Exercise, Daily

# Créer un exercice si aucun n'existe
if not Exercise.objects.exists():
    year = datetime.now().year
    exercise = Exercise.objects.create(
        start_date=datetime(year, 1, 1),
        end_date=None  # Exercice ouvert
    )
    print(f"✅ Exercice créé pour l'année {year}")
else:
    exercise = Exercise.objects.first()
    print(f"ℹ️  Exercice existant: {exercise}")

# Créer une session Daily pour aujourd'hui si elle n'existe pas
now = datetime.now()
# Chercher une session Daily ouverte (sans end_date)
daily = Daily.objects.filter(end_date__isnull=True, exercise=exercise).first()

if not daily:
    daily = Daily.objects.create(
        start_date=now,
        end_date=None,  # Session ouverte
        exercise=exercise
    )
    print(f"✅ Session Daily créée")
else:
    print(f"ℹ️  Session Daily existante")

print("\n📊 Résumé:")
print(f"   - Exercice: {exercise}")
print(f"   - Session Daily ID: {daily.id}")
print(f"   - Début: {daily.start_date}")
print(f"   - Statut: {'Fermée' if daily.end_date else 'Ouverte'}")

