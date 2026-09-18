"""
Backend d'authentification et authentification DRF qui refusent les comptes
désactivés OU soft-supprimés (``delete_at`` renseigné).

Django et DRF ne testent par défaut que ``is_active`` ; un compte « supprimé »
par ``delete_at`` pouvait donc encore se connecter et rejouer son token.
"""

from django.contrib.auth.backends import ModelBackend
from django.utils.translation import gettext as _
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


def user_is_usable(user) -> bool:
    """Un compte est utilisable s'il est actif et non soft-supprimé."""
    return bool(
        user is not None
        and getattr(user, 'is_active', False)
        and getattr(user, 'delete_at', None) is None
    )


class ActiveStaffBackend(ModelBackend):
    """ModelBackend qui refuse aussi les comptes soft-supprimés."""

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and getattr(user, 'delete_at', None) is None


class ActiveStaffTokenAuthentication(TokenAuthentication):
    """TokenAuthentication qui refuse les tokens de comptes soft-supprimés."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if not user_is_usable(user):
            raise exceptions.AuthenticationFailed(_("Compte désactivé."))
        return user, token
