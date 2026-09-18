"""
Serializers for authentication endpoints.
"""

from rest_framework import serializers
from django.contrib.auth import authenticate
from django.utils.translation import gettext

from core.models import CustomUser


class LoginSerializer(serializers.Serializer):
    """
    Serializer pour l'authentification.
    Correspond à l'ancien endpoint Flask: GET /login/<login>/<password>
    """
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True, trim_whitespace=False)

    def validate(self, data):
        username = data.get('username')
        password = data.get('password')

        user = authenticate(username=username, password=password)
        if not user:
            # Distinguer un compte inscrit mais pas encore activé (mot de passe
            # correct) d'identifiants invalides, sans révéler l'existence
            # d'un compte à qui ne connaît pas le mot de passe.
            candidate = CustomUser.objects.filter(username=username).first()
            if (candidate and candidate.check_password(password)
                    and candidate.delete_at is None and not candidate.is_active):
                raise serializers.ValidationError(
                    gettext("Ce compte n'est pas encore activé par un administrateur.")
                )
            raise serializers.ValidationError(gettext("Identifiants invalides."))
        if user.delete_at is not None:
            raise serializers.ValidationError(gettext("Ce compte a été désactivé."))

        data['user'] = user
        return data
