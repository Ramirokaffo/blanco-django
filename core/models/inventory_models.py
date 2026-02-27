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
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='supplies', verbose_name="Produit")
    supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies', verbose_name="Fournisseur")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies', verbose_name="Personnel")
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='supplies', verbose_name="Journée")
    quantity = models.IntegerField(verbose_name="Quantité")
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Prix d'achat")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Prix de vente")
    total_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Prix total")
    expiration_date = models.DateField(null=True, blank=True, verbose_name="Date d'expiration")
    is_credit = models.BooleanField(default=False, verbose_name="Achat à crédit")
    is_paid = models.BooleanField(default=True, verbose_name="Entièrement payé")
    
    class Meta:
        db_table = 'supply'
        # managed = False
        verbose_name = 'Approvisionnement'
        verbose_name_plural = 'Approvisionnements'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Approvisionnement {self.product.name} x{self.quantity}"
    
    def get_total(self):
        """Calculate total price."""
        return self.quantity * self.purchase_cost


class Inventory(SoftDeleteModel):
    """
    Inventory count model.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventories', verbose_name="Produit")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventories', verbose_name="Personnel")
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventories', verbose_name="Exercice")
    valid_product_count = models.IntegerField(default=0, verbose_name="Produits valides")
    invalid_product_count = models.IntegerField(default=0, verbose_name="Produits invalides")
    is_close = models.BooleanField(default=False, verbose_name="Clôturé")
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")

    class Meta:
        db_table = 'inventory'
        # managed = False
        verbose_name = 'Inventaire'
        verbose_name_plural = 'Inventaires'
        ordering = ['-create_at']

    def __str__(self):
        return f"Inventaire {self.product.name} - {self.create_at.strftime('%Y-%m-%d')}"

    def total_count(self):
        """Calculate total product count (valid + invalid)."""
        return self.valid_product_count + self.invalid_product_count


class InventorySnapshot(SoftDeleteModel):
    """
    Snapshot de l'état d'un produit au moment de la clôture d'inventaire.
    Permet de faire un bilan de l'inventaire par la suite.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventory_snapshots', verbose_name="Produit")
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventory_snapshots', verbose_name="Exercice")
    stock_before = models.IntegerField(help_text="Stock du produit avant la clôture", verbose_name="Stock avant")
    total_counted = models.IntegerField(help_text="Quantité totale comptée (valide + invalide) cumulée", verbose_name="Total compté")
    total_valid = models.IntegerField(help_text="Quantité valide cumulée", verbose_name="Total valide")
    total_invalid = models.IntegerField(help_text="Quantité invalide cumulée", verbose_name="Total invalide")
    stock_after = models.IntegerField(help_text="Stock du produit après la clôture (= total_valid)", verbose_name="Stock après")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Prix de vente au moment de la clôture", verbose_name="Prix de vente")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Prix d'achat au moment de la clôture", verbose_name="Prix d'achat")

    class Meta:
        db_table = 'inventory_snapshot'
        verbose_name = 'Resumé d\'inventaire'
        verbose_name_plural = 'Resumés d\'inventaire'
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
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='inventories', verbose_name="Journée")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='daily_inventories', verbose_name="Personnel")
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='daily_inventories', verbose_name="Exercice")
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total ventes")
    total_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total dépenses")
    total_recipes = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total recettes")
    cash_in_hand = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Fond de caisse")
    cash_float = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Fond de caisse pour le lendemain", verbose_name="Fond de caisse pour le lendemain")
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")

    class Meta:
        db_table = 'daily_inventory'
        # managed = False
        verbose_name = 'Inventaire journalière'
        verbose_name_plural = 'Inventaires journalière'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Inventaire journalière {self.daily}"
    
    def get_net_balance(self):
        """Calculate net balance for the day."""
        return self.total_sales + self.total_recipes - self.total_expenses


class CreditSupply(SoftDeleteModel):
    """
    Suivi des approvisionnements à crédit (dettes fournisseurs).
    Miroir de CreditSale pour le côté fournisseur.
    """
    supply = models.OneToOneField(Supply, on_delete=models.CASCADE, related_name='credit_info')
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Montant payé")
    amount_remaining = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant restant")
    due_date = models.DateField(null=True, blank=True, verbose_name="Date d'échéance")
    is_fully_paid = models.BooleanField(default=False, verbose_name="Entièrement payé")

    class Meta:
        db_table = 'credit_supply'
        verbose_name = 'Approvisionnement à crédit'
        verbose_name_plural = 'Approvisionnements à crédit'
        ordering = ['-supply__create_at']

    def __str__(self):
        return f"Crédit fournisseur – Appro. #{self.supply_id}"

    def get_remaining_balance(self):
        """Calcul du solde restant."""
        return self.supply.total_price - self.amount_paid if self.supply.total_price else 0


class PaymentSchedule(SoftDeleteModel):
    """
    Échéancier de paiement : une ligne par échéance planifiée.
    Peut être lié à un CreditSale (créance client) ou CreditSupply (dette fournisseur).
    """
    SCHEDULE_TYPE_CHOICES = [
        ('CLIENT', 'Créance client'),
        ('SUPPLIER', 'Dette fournisseur'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('PARTIAL', 'Partiellement payé'),
        ('PAID', 'Payé'),
        ('OVERDUE', 'En retard'),
    ]

    schedule_type = models.CharField(max_length=10, choices=SCHEDULE_TYPE_CHOICES, verbose_name="Type")
    credit_sale = models.ForeignKey(
        'CreditSale', on_delete=models.CASCADE, null=True, blank=True,
        related_name='schedules', verbose_name="Vente à crédit"
    )
    credit_supply = models.ForeignKey(
        CreditSupply, on_delete=models.CASCADE, null=True, blank=True,
        related_name='schedules', verbose_name="Approvisionnement à crédit"
    )
    due_date = models.DateField(verbose_name="Date d'échéance")
    amount_due = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant dû")
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Montant payé")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', verbose_name="Statut")
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")

    class Meta:
        db_table = 'payment_schedule'
        verbose_name = 'Échéance de paiement'
        verbose_name_plural = 'Échéances de paiement'
        ordering = ['due_date']

    def __str__(self):
        return f"Échéance {self.due_date} – {self.amount_due} FCFA ({self.get_status_display()})"

    @property
    def amount_remaining(self):
        return self.amount_due - self.amount_paid

    @property
    def is_overdue(self):
        from datetime import date
        return self.status != 'PAID' and self.due_date < date.today()

    def update_status(self):
        """Met à jour le statut en fonction du paiement et de la date."""
        from datetime import date
        if self.amount_paid >= self.amount_due:
            self.status = 'PAID'
        elif self.amount_paid > 0:
            self.status = 'PARTIAL'
        elif self.due_date < date.today():
            self.status = 'OVERDUE'
        else:
            self.status = 'PENDING'

