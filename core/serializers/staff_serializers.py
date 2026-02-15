"""
Serializers for staff/user endpoints.
Correspond aux anciens endpoints Flask:
  - GET /get_user_by_id/<user_id>
  - GET /get_staff_by_login/<login>
  - POST /create_user
  - POST /update_user
"""

from rest_framework import serializers
from core.models import CustomUser


class StaffSerializer(serializers.ModelSerializer):
    """Serializer de lecture pour un utilisateur/staff."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'firstname', 'lastname', 'full_name',
            'phone_number', 'role', 'gender', 'profil',
            'is_active', 'create_at',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


class StaffCreateSerializer(serializers.ModelSerializer):
    """
    Serializer pour créer un utilisateur.
    Correspond à l'ancien endpoint Flask: POST /create_user
    """
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = CustomUser
        fields = [
            'username', 'password', 'firstname', 'lastname',
            'phone_number', 'role', 'gender', 'profil',
        ]

    def validate_username(self, value):
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur existe déjà.")
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = CustomUser(**validated_data)
        user.set_password(password)
        user.save()
        return user


class StaffUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour mettre à jour un utilisateur.
    Correspond à l'ancien endpoint Flask: POST /update_user
    """
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = CustomUser
        fields = [
            'username', 'password', 'firstname', 'lastname',
            'phone_number', 'role', 'gender', 'profil',
        ]
        extra_kwargs = {
            'username': {'required': False},
        }

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

