"""
Inventory-related models: Supply, Inventory, DailyInventory.
"""

from django.db import models
from django.conf import settings

from core.models.base_models import SoftDeleteModel


class Supply(SoftDeleteModel):
    """
    Supply/Stock replenishment model.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='supplies')
    supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies')
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='supplies')
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    expiration_date = models.DateField(null=True, blank=True)
    
    class Meta:
        db_table = 'supply'
        # managed = False
        verbose_name = 'Supply'
        verbose_name_plural = 'Supplies'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Supply {self.product.name} x{self.quantity}"
    
    def get_total(self):
        """Calculate total price."""
        return self.quantity * self.unit_price


class Inventory(SoftDeleteModel):
    """
    Inventory count model.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventories')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventories')
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventories')
    quantity_counted = models.IntegerField()
    quantity_system = models.IntegerField()
    difference = models.IntegerField(default=0)
    notes = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'inventory'
        # managed = False
        verbose_name = 'Inventory'
        verbose_name_plural = 'Inventories'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Inventory {self.product.name} - {self.create_at.strftime('%Y-%m-%d')}"
    
    def calculate_difference(self):
        """Calculate difference between counted and system quantity."""
        return self.quantity_counted - self.quantity_system


class DailyInventory(SoftDeleteModel):
    """
    Daily inventory summary model.
    """
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='inventories')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='daily_inventories')
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='daily_inventories')
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_recipes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_in_hand = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'daily_inventory'
        # managed = False
        verbose_name = 'Daily Inventory'
        verbose_name_plural = 'Daily Inventories'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Daily Inventory {self.daily}"
    
    def get_net_balance(self):
        """Calculate net balance for the day."""
        return self.total_sales + self.total_recipes - self.total_expenses

