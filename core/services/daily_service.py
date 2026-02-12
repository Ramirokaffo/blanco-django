
from core.models.accounting_models import Daily
from datetime import datetime, timezone

from core.services.excercise_service import ExerciseService


class DailyService:

    @staticmethod
    def get_or_create_active_daily():
        
        current_daily = Daily.objects.filter(end_date__isnull=True).order_by('-start_date').first()
        if not current_daily: # Si aucun Daily actif n'existe, en créer un nouveau
            current_exercise = ExerciseService().get_or_create_current_exercise()
            current_daily = Daily.objects.create(start_date=datetime.now(), exercise=current_exercise)
            current_daily.save()
        return current_daily
    
    @staticmethod
    def close_current_daily():
        current_daily = Daily.objects.filter(end_date__isnull=True).order_by('-start_date').first()
        if current_daily:
            current_daily.end_date = datetime.now()
            current_daily.save()
        return current_daily



