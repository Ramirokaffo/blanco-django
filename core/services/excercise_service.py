
from core.models.accounting_models import Exercise
from datetime import date

class ExerciseService:

    @staticmethod
    def get_or_create_current_exercise(): 
        """Récupérer l'exercice actif (non fermé)"""
        exercise = Exercise.objects.filter(end_date__isnull=True).order_by('-start_date').first()
        if not exercise:
            exercise = Exercise.objects.create(start_date=date.today())
        return exercise