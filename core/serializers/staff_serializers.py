"""
Serializers for staff/user endpoints.
Correspond aux anciens endpoints Flask:
  - GET /get_user_by_id/<user_id>
  - GET /get_staff_by_login/<login>
  - POST /create_user
  - POST /update_user
"""

from django.contrib.auth import password_validation
from django.core import exceptions as django_exceptions
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from core.models import CustomUser


class StaffSerializer(serializers.ModelSerializer):
    """Serializer de lecture pour un utilisateur/staff."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'firstname', 'lastname', 'full_name',
            'phone_number', 'role', 'gender', 'profil',
            'is_active',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


def _validate_password_strength(password, user=None):
    try:
        password_validation.validate_password(password, user=user)
    except django_exceptions.ValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return password


class StaffCreateSerializer(serializers.ModelSerializer):
    """
    Serializer pour créer un utilisateur.
    Correspond à l'ancien endpoint Flask: POST /create_user
    Les champs sensibles (is_active, is_staff, is_superuser, allowed_modules)
    ne sont volontairement pas exposés.
    """
    password = serializers.CharField(write_only=True, required=True, trim_whitespace=False)

    class Meta:
        model = CustomUser
        fields = [
            'username', 'firstname', 'lastname',
            'phone_number', 'role', 'gender', "password", 'profil',
        ]

    def validate_username(self, value):
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError(gettext("Ce nom d'utilisateur existe déjà."))
        return value

    def validate(self, data):
        # Validation de la robustesse avec les attributs de l'utilisateur
        probe = CustomUser(**{k: v for k, v in data.items() if k != 'password'})
        _validate_password_strength(data['password'], user=probe)
        return data

    def create(self, validated_data):
        password = validated_data.pop('password')
        is_active = validated_data.pop('is_active', False)
        user = CustomUser(**validated_data)
        user.is_active = is_active
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        user.save()
        return user


class StaffUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour mettre à jour un utilisateur.
    Correspond à l'ancien endpoint Flask: POST /update_user

    - ``username`` et ``role`` ne sont modifiables que par un superuser ;
    - un utilisateur qui change SON mot de passe doit fournir ``current_password`` ;
    - tout changement de mot de passe révoque les tokens existants.
    """
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    current_password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)

    ADMIN_ONLY_FIELDS = ('username', 'role')

    class Meta:
        model = CustomUser
        fields = [
            'username', 'password', 'current_password', 'firstname', 'lastname',
            'phone_number', 'role', 'gender', 'profil',
        ]
        extra_kwargs = {
            'username': {'required': False},
        }

    password_changed = False

    def _requester(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def validate(self, data):
        requester = self._requester()
        is_admin = bool(requester and requester.is_superuser)
        is_self = bool(requester and self.instance and requester.pk == self.instance.pk)

        if not is_admin:
            forbidden = [f for f in self.ADMIN_ONLY_FIELDS if f in data]
            if forbidden:
                raise serializers.ValidationError({
                    f: gettext("Seul un administrateur peut modifier ce champ.") for f in forbidden
                })

        password = data.get('password')
        if password:
            if is_self and not is_admin:
                current = data.get('current_password')
                if not current or not self.instance.check_password(current):
                    raise serializers.ValidationError({
                        'current_password': gettext("Mot de passe actuel incorrect.")
                    })
            _validate_password_strength(password, user=self.instance)
        data.pop('current_password', None)
        return data

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
            self.password_changed = True
        instance.save()
        if password:
            # Révoquer les tokens existants : un mot de passe changé
            # invalide les sessions API précédentes.
            Token.objects.filter(user=instance).delete()
        return instance
