"""
Script pour créer un superutilisateur Django.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blanco.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Créer un superutilisateur si il n'existe pas
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(
        username='admin',
        email='admin@blanco.com',
        password='admin123'
    )
    print("✅ Superutilisateur créé avec succès!")
    print("   Username: admin")
    print("   Password: admin123")
    print("\n⚠️  N'oubliez pas de changer le mot de passe en production!")
else:
    print("ℹ️  Le superutilisateur 'admin' existe déjà.")

