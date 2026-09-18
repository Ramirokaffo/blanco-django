"""
Gestion des journées (Daily) : une seule journée ouverte à la fois.
"""

from django.db import transaction
from django.utils import timezone

from core.models.accounting_models import Daily, Exercise
from core.services.excercise_service import ExerciseService


class DailyService:

    @staticmethod
    def get_active_daily():
        """Retourne la journée ouverte (lecture seule, ne crée rien)."""
        return Daily.objects.filter(
            end_date__isnull=True, delete_at__isnull=True,
        ).order_by('-start_date').first()

    @staticmethod
    def get_or_create_active_daily():
        """Retourne la journée ouverte, ou en crée une (création sérialisée)."""
        current_daily = DailyService.get_active_daily()
        if current_daily:
            return current_daily
        with transaction.atomic():
            current_exercise = ExerciseService.get_or_create_current_exercise()
            # Verrou sur l'exercice : deux requêtes simultanées ne créent
            # pas deux journées ouvertes (MySQL ; no-op sous SQLite).
            Exercise.objects.select_for_update().filter(pk=current_exercise.pk).first()
            current_daily = DailyService.get_active_daily()
            if not current_daily:
                current_daily = Daily.objects.create(
                    start_date=timezone.now(), exercise=current_exercise,
                )
        return current_daily

    @staticmethod
    def close_current_daily():
        """Ferme la journée ouverte (idempotent) et la retourne, ou None."""
        with transaction.atomic():
            current_daily = Daily.objects.select_for_update().filter(
                end_date__isnull=True, delete_at__isnull=True,
            ).order_by('-start_date').first()
            if current_daily:
                current_daily.end_date = timezone.now()
                current_daily.save(update_fields=['end_date'])
        return current_daily
