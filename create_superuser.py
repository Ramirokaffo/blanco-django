#!/usr/bin/env python
"""
Crée le superutilisateur initial s'il n'existe pas.

Le mot de passe est lu dans la variable d'environnement
``DJANGO_SUPERUSER_PASSWORD`` ; s'il n'est pas fourni, un mot de passe aléatoire
est généré et affiché UNE SEULE FOIS. Plus aucun mot de passe par défaut.

    DJANGO_SUPERUSER_PASSWORD='un-mot-de-passe-solide' python create_superuser.py
"""
import os
import secrets
import sys

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blanco.settings')
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402

User = get_user_model()

USERNAME = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
EMAIL = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@blanco.local')

if User.objects.filter(username=USERNAME).exists():
    print(f"ℹ️  Le superutilisateur '{USERNAME}' existe déjà.")
    sys.exit(0)

password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
generated = False
if not password:
    password = secrets.token_urlsafe(12)
    generated = True
else:
    try:
        validate_password(password)
    except ValidationError as exc:
        print("❌ Mot de passe refusé :")
        for message in exc.messages:
            print(f"   - {message}")
        sys.exit(1)

User.objects.create_superuser(username=USERNAME, email=EMAIL, password=password)
print(f"✅ Superutilisateur '{USERNAME}' créé.")
if generated:
    print("   Mot de passe généré (notez-le, il ne sera plus affiché) :")
    print(f"   {password}")
