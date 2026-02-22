"""
Accounting-related models: Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense.
"""

from django.db import models
from django.conf import settings

from core.models.base_models import SoftDeleteModel


class Exercise(SoftDeleteModel):
    """
    Fiscal exercise/year model.
    """
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'exercise'
        # managed = False
        verbose_name = 'Exercice'
        verbose_name_plural = 'Exercices'
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Exercice {self.start_date.year if self.start_date else self.id}"
    
    def is_active(self):
        """Check if the exercise is currently active."""
        return self.end_date is None


class Daily(SoftDeleteModel):
    """
    Daily session model for tracking daily operations.
    """
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='dailies')
    
    class Meta:
        db_table = 'daily'
        # managed = False
        verbose_name = 'Journée'
        verbose_name_plural = 'Journées'
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Journée {self.start_date.strftime('%Y-%m-%d') if self.start_date else self.id}"
    
    def is_open(self):
        """Check if the daily session is still open."""
        return self.end_date is None


class ExpenseType(SoftDeleteModel):
    """
    Type of expense model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'expense_type'
        # managed = False
        verbose_name = 'Type de dépense'
        verbose_name_plural = 'Types de dépenses'
    
    def __str__(self):
        return self.name


class RecipeType(SoftDeleteModel):
    """
    Type of recipe/income model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'recipe_type'
        # managed = False
        verbose_name = 'Type de recette'
        verbose_name_plural = 'Types de recettes'
    
    def __str__(self):
        return self.name


class DailyExpense(SoftDeleteModel):
    """
    Daily expense model.
    """
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    daily = models.ForeignKey(Daily, on_delete=models.CASCADE, related_name='expenses')
    expense_type = models.ForeignKey(ExpenseType, on_delete=models.SET_NULL, null=True, related_name='daily_expenses')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='expenses')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='expenses')
    
    class Meta:
        db_table = 'daily_expense'
        # managed = False
        verbose_name = 'Dépense quotidienne'
        verbose_name_plural = 'Dépenses quotidiennes'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Dépense {self.amount} - {self.expense_type}"


class DailyRecipe(SoftDeleteModel):
    """
    Daily recipe/income model.
    """
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    daily = models.ForeignKey(Daily, on_delete=models.CASCADE, related_name='recipes')
    recipe_type = models.ForeignKey(RecipeType, on_delete=models.SET_NULL, null=True, related_name='daily_recipes')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='recipes')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='recipes')
    
    class Meta:
        db_table = 'daily_recipe'
        # managed = False
        verbose_name = 'Recette quotidienne'
        verbose_name_plural = 'Recettes quotidiennes'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Recette {self.amount} - {self.recipe_type}"


class ProductExpense(SoftDeleteModel):
    """
    Product expense model for tracking product-related expenses.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='expenses')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'product_expense'
        # managed = False
        verbose_name = 'Dépense produit'
        verbose_name_plural = 'Dépenses produits'
    
    def __str__(self):
        return f"Dépense {self.amount} pour {self.product.name}"

