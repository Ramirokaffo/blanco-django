"""
Service d'authentification.
"""

from rest_framework.authtoken.models import Token
from core.models import CustomUser


class AuthService:

    @staticmethod
    def get_or_create_token(user: CustomUser) -> str:
        """Crée ou récupère le token d'authentification pour un utilisateur."""
        token, _ = Token.objects.get_or_create(user=user)
        return token.key

