"""
Permissions DRF alignées sur le modèle d'accès du back-office.

- ``IsSuperUser`` : réservé aux superutilisateurs.
- ``HasModule('sales', 'products')`` : l'utilisateur doit avoir accès à au
  moins un des modules listés (les superusers passent toujours, comme pour
  le décorateur ``module_required`` des vues HTML).
- ``IsSelfOrSuperUser`` : l'objet manipulé est l'utilisateur lui-même, ou
  l'appelant est superuser.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import BasePermission


class IsSuperUser(BasePermission):
    message = _("Réservé aux administrateurs.")

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


def HasModule(*module_codes):
    """Fabrique une classe de permission exigeant l'un des modules donnés."""

    codes = tuple(module_codes)

    class _HasModule(BasePermission):
        message = _(
            "Vous n'avez pas accès à ce module. "
            "Contactez votre administrateur."
        )

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            if user.is_superuser:
                return True
            return any(user.has_module_access(code) for code in codes)

    _HasModule.__name__ = f"HasModule({', '.join(codes)})"
    return _HasModule


class IsSelfOrSuperUser(BasePermission):
    message = _("Vous ne pouvez modifier que votre propre compte.")

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        return bool(user.is_superuser or obj.pk == user.pk)
