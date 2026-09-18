"""
Gestion des exercices comptables : un seul exercice ouvert à la fois.
"""

from django.db import transaction
from django.utils import timezone

from core.models.accounting_models import Exercise


class ExerciseService:

    @staticmethod
    def get_current_exercise():
        """Retourne l'exercice ouvert (lecture seule, ne crée rien)."""
        return Exercise.objects.filter(
            end_date__isnull=True, delete_at__isnull=True,
        ).order_by('-start_date').first()

    @staticmethod
    def get_or_create_current_exercise():
        """Récupérer l'exercice actif (non fermé), le créer s'il n'existe pas."""
        exercise = ExerciseService.get_current_exercise()
        if exercise:
            return exercise
        with transaction.atomic():
            # Re-vérifier sous verrou de table logique (dernier exercice)
            last = Exercise.objects.select_for_update().order_by('-start_date').first()
            if last and last.end_date is None and last.delete_at is None:
                return last
            exercise = Exercise.objects.create(start_date=timezone.now())
        return exercise
