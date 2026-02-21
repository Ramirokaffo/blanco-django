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
    valid_product_count = models.IntegerField(default=0)
    invalid_product_count = models.IntegerField(default=0)
    is_close = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'inventory'
        # managed = False
        verbose_name = 'Inventory'
        verbose_name_plural = 'Inventories'
        ordering = ['-create_at']

    def __str__(self):
        return f"Inventory {self.product.name} - {self.create_at.strftime('%Y-%m-%d')}"

    def total_count(self):
        """Calculate total product count (valid + invalid)."""
        return self.valid_product_count + self.invalid_product_count


class InventorySnapshot(SoftDeleteModel):
    """
    Snapshot de l'état d'un produit au moment de la clôture d'inventaire.
    Permet de faire un bilan de l'inventaire par la suite.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventory_snapshots')
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventory_snapshots')
    stock_before = models.IntegerField(help_text="Stock du produit avant la clôture")
    total_counted = models.IntegerField(help_text="Quantité totale comptée (valide + invalide) cumulée")
    total_valid = models.IntegerField(help_text="Quantité valide cumulée")
    total_invalid = models.IntegerField(help_text="Quantité invalide cumulée")
    stock_after = models.IntegerField(help_text="Stock du produit après la clôture (= total_valid)")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Prix de vente (actual_price) au moment de la clôture")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Prix d'achat (last_purchase_price) au moment de la clôture")

    class Meta:
        db_table = 'inventory_snapshot'
        verbose_name = 'Inventory Snapshot'
        verbose_name_plural = 'Inventory Snapshots'
        ordering = ['-create_at']
        unique_together = [('product', 'exercise')]

    def __str__(self):
        return f"Snapshot {self.product.name} - Exercise {self.exercise_id}"

    def stock_difference(self):
        """Différence entre le stock avant et la quantité valide comptée."""
        return self.total_valid - self.stock_before


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
    cash_float = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Fond de caisse pour le lendemain")
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

