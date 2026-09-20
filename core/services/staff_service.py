"""
Service pour la gestion du personnel (Staff / CustomUser).
"""

from django.utils.translation import gettext as _

from core.models import CustomUser


class StaffService:

    @staticmethod
    def get_by_id(user_id: int):
        """Récupère un utilisateur par son ID."""
        return CustomUser.objects.filter(
            id=user_id, delete_at__isnull=True
        ).first()

    @staticmethod
    def get_by_username(username: str):
        """Récupère un utilisateur par son nom d'utilisateur."""
        return CustomUser.objects.filter(
            username=username, delete_at__isnull=True
        ).first()

    @staticmethod
    def get_active_staff():
        """Récupère tous les utilisateurs actifs."""
        return CustomUser.objects.filter(
            is_active=True, delete_at__isnull=True
        )

    # ── Protection du dernier administrateur ───────────────────────────

    @staticmethod
    def count_active_superusers(exclude_pk=None) -> int:
        """Nombre d'administrateurs actifs et non supprimés."""
        queryset = CustomUser.objects.filter(
            is_superuser=True, is_active=True, delete_at__isnull=True
        )
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.count()

    @staticmethod
    def is_last_active_superuser(user) -> bool:
        """Vrai si retirer cet utilisateur ne laisserait aucun administrateur."""
        if user is None or not user.is_superuser:
            return False
        if not user.is_active or user.delete_at is not None:
            return False
        return StaffService.count_active_superusers(exclude_pk=user.pk) == 0

    @staticmethod
    def ensure_not_last_superuser(user):
        """
        Refuse de désactiver, supprimer ou rétrograder le dernier administrateur.

        Sans ce garde-fou, le responsable d'un espace peut se retirer ses
        propres droits et s'enfermer dehors : plus personne ne peut alors
        gérer les utilisateurs ni les paramètres, et seule une intervention
        manuelle sur la base permet de rouvrir l'accès. En hébergement
        mutualisé, cela signifie un ticket de support et un accès aux données
        du client — précisément ce que l'on cherche à éviter.
        """
        if StaffService.is_last_active_superuser(user):
            raise ValueError(_(
                "Vous ne pouvez pas retirer les droits du dernier "
                "administrateur de l'espace. Nommez d'abord un autre "
                "administrateur."
            ))
