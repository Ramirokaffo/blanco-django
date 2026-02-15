"""
Service pour la gestion du personnel (Staff / CustomUser).
"""

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

