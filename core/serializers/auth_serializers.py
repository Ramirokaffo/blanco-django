"""
Serializers for authentication endpoints.
"""

from rest_framework import serializers
from django.contrib.auth import authenticate


class LoginSerializer(serializers.Serializer):
    """
    Serializer pour l'authentification.
    Correspond à l'ancien endpoint Flask: GET /login/<login>/<password>
    """
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, data):
        username = data.get('username')
        password = data.get('password')

        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("Identifiants invalides.")
        if user.delete_at is not None:
            raise serializers.ValidationError("Ce compte a été désactivé.")

        data['user'] = user
        return data

