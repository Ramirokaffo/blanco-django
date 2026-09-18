"""
Inventory-related models: Supply, Inventory, DailyInventory.
"""

from django.db import models
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy
from django.conf import settings

from core.models.base_models import SoftDeleteModel


class Supply(SoftDeleteModel):
    """
    Supply/Stock replenishment model.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='supplies', verbose_name=_("Produit"))
    supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies', verbose_name=_("Fournisseur"))
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies', verbose_name=_("Personnel"))
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='supplies', verbose_name=_("Journée"))
    quantity = models.IntegerField(verbose_name=_("Quantité"))
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Prix d'achat"))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_("Prix de vente"))
    total_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Prix total"))
    expiration_date = models.DateField(null=True, blank=True, verbose_name=_("Date d'expiration"))
    is_credit = models.BooleanField(default=False, verbose_name=_("Achat à crédit"))
    is_paid = models.BooleanField(default=True, verbose_name=_("Entièrement payé"))
    
    # Champs TVA
    tax_rate = models.ForeignKey(
        'core.TaxRate', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='supplies',
        verbose_name=_("Taux de TVA")
    )
    vat_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0,
        verbose_name=_("Montant TVA")
    )
    
    # Type de dépense pour l'approvisionnement
    expense_type = models.ForeignKey(
        'core.ExpenseType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplies',
        verbose_name=_("Type de dépense")
    )
    
    class Meta:
        db_table = 'supply'
        # managed = False
        # Contexte : le même mot sert de libellé de menu (module « Approvisionnement » → Supplies)
        verbose_name = pgettext_lazy('nom de modèle', 'Approvisionnement')
        verbose_name_plural = _('Approvisionnements')
        ordering = ['-create_at']
    
    def __str__(self):
        return gettext("Approvisionnement %(product)s x%(quantity)s") % {'product': self.product.name, 'quantity': self.quantity}
    
    def get_total(self):
        """Calculate total price."""
        return self.quantity * self.purchase_cost


class SupplyReturn(SoftDeleteModel):
    """Trace d'un retour partiel fournisseur sur un approvisionnement."""

    supply = models.ForeignKey(Supply, on_delete=models.CASCADE, related_name='supply_returns')
    quantity = models.IntegerField(default=1, verbose_name=_("Quantité retournée"))
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Coût unitaire"))
    total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Montant retourné"))
    reason = models.TextField(null=True, blank=True, verbose_name=_("Motif"))
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("Remboursement reçu"))
    refund_payment_method = models.CharField(max_length=20, null=True, blank=True, verbose_name=_("Mode de remboursement"))

    class Meta:
        db_table = 'supply_return'
        verbose_name = _('Retour fournisseur')
        verbose_name_plural = _('Retours fournisseurs')
        ordering = ['-create_at']

    def __str__(self):
        return gettext("Retour %(total)s pour Appro. #%(supply_id)s") % {'total': self.total, 'supply_id': self.supply_id}


class Inventory(SoftDeleteModel):
    """
    Inventory count model.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventories', verbose_name=_("Produit"))
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventories', verbose_name=_("Personnel"))
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventories', verbose_name=_("Exercice"))
    valid_product_count = models.IntegerField(default=0, verbose_name=_("Produits valides"))
    invalid_product_count = models.IntegerField(default=0, verbose_name=_("Produits invalides"))
    is_close = models.BooleanField(default=False, verbose_name=_("Clôturé"))
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))

    class Meta:
        db_table = 'inventory'
        # managed = False
        verbose_name = _('Inventaire')
        verbose_name_plural = _('Inventaires')
        ordering = ['-create_at']

    def __str__(self):
        return gettext("Inventaire %(product)s - %(date)s") % {'product': self.product.name, 'date': self.create_at.strftime('%Y-%m-%d')}

    def total_count(self):
        """Calculate total product count (valid + invalid)."""
        return self.valid_product_count + self.invalid_product_count


class InventorySnapshot(SoftDeleteModel):
    """
    Snapshot de l'état d'un produit au moment de la clôture d'inventaire.
    Permet de faire un bilan de l'inventaire par la suite.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='inventory_snapshots', verbose_name=_("Produit"))
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='inventory_snapshots', verbose_name=_("Exercice"))
    stock_before = models.IntegerField(help_text=_("Stock du produit avant la clôture"), verbose_name=_("Stock avant"))
    total_counted = models.IntegerField(help_text=_("Quantité totale comptée (valide + invalide) cumulée"), verbose_name=_("Total compté"))
    total_valid = models.IntegerField(help_text=_("Quantité valide cumulée"), verbose_name=_("Total valide"))
    total_invalid = models.IntegerField(help_text=_("Quantité invalide cumulée"), verbose_name=_("Total invalide"))
    stock_after = models.IntegerField(help_text=_("Stock du produit après la clôture (= total_valid)"), verbose_name=_("Stock après"))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text=_("Prix de vente au moment de la clôture"), verbose_name=_("Prix de vente"))
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text=_("Prix d'achat au moment de la clôture"), verbose_name=_("Prix d'achat"))

    class Meta:
        db_table = 'inventory_snapshot'
        verbose_name = _('Resumé d\'inventaire')
        verbose_name_plural = _('Resumés d\'inventaire')
        ordering = ['-create_at']
        unique_together = [('product', 'exercise')]

    def __str__(self):
        return gettext("Snapshot %(product)s - Exercise %(exercise_id)s") % {'product': self.product.name, 'exercise_id': self.exercise_id}

    def stock_difference(self):
        """Différence entre le stock avant et la quantité valide comptée."""
        return self.total_valid - self.stock_before


class DailyInventory(SoftDeleteModel):
    """
    Daily inventory summary model.
    """
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='inventories', verbose_name=_("Journée"))
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='daily_inventories', verbose_name=_("Personnel"))
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='daily_inventories', verbose_name=_("Exercice"))
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("Total ventes"))
    total_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("Total dépenses"))
    total_recipes = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("Total recettes"))
    cash_in_hand = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("Fond de caisse"))
    cash_float = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Fond de caisse pour le lendemain"), verbose_name=_("Fond de caisse pour le lendemain"))
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))

    class Meta:
        db_table = 'daily_inventory'
        # managed = False
        verbose_name = _('Inventaire journalière')
        verbose_name_plural = _('Inventaires journalière')
        ordering = ['-create_at']
    
    def __str__(self):
        return gettext("Inventaire journalière %(daily)s") % {'daily': self.daily}
    
    def get_net_balance(self):
        """Calculate net balance for the day."""
        return self.total_sales + self.total_recipes - self.total_expenses


class CreditSupply(SoftDeleteModel):
    """
    Suivi des approvisionnements à crédit (dettes fournisseurs).
    Miroir de CreditSale pour le côté fournisseur.
    """
    supply = models.OneToOneField(Supply, on_delete=models.CASCADE, related_name='credit_info')
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name=_("Montant payé"))
    amount_remaining = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Montant restant"))
    due_date = models.DateField(null=True, blank=True, verbose_name=_("Date d'échéance"))
    is_fully_paid = models.BooleanField(default=False, verbose_name=_("Entièrement payé"))

    class Meta:
        db_table = 'credit_supply'
        verbose_name = _('Approvisionnement à crédit')
        verbose_name_plural = _('Approvisionnements à crédit')
        ordering = ['-supply__create_at']

    def __str__(self):
        return gettext("Crédit fournisseur – Appro. #%(supply_id)s") % {'supply_id': self.supply_id}

    def get_remaining_balance(self):
        """Calcul du solde restant."""
        return self.supply.total_price - self.amount_paid if self.supply.total_price else 0


class PaymentSchedule(SoftDeleteModel):
    """
    Échéancier de paiement : une ligne par échéance planifiée.
    Peut être lié à un CreditSale (créance client) ou CreditSupply (dette fournisseur).
    """
    SCHEDULE_TYPE_CHOICES = [
        ('CLIENT', _('Créance client')),
        ('SUPPLIER', _('Dette fournisseur')),
    ]
    STATUS_CHOICES = [
        ('PENDING', _('En attente')),
        ('PARTIAL', _('Partiellement payé')),
        ('PAID', _('Payé')),
        ('OVERDUE', _('En retard')),
    ]

    schedule_type = models.CharField(max_length=10, choices=SCHEDULE_TYPE_CHOICES, verbose_name=_("Type"))
    credit_sale = models.ForeignKey(
        'CreditSale', on_delete=models.CASCADE, null=True, blank=True,
        related_name='schedules', verbose_name=_("Vente à crédit")
    )
    credit_supply = models.ForeignKey(
        CreditSupply, on_delete=models.CASCADE, null=True, blank=True,
        related_name='schedules', verbose_name=_("Approvisionnement à crédit")
    )
    due_date = models.DateField(verbose_name=_("Date d'échéance"))
    amount_due = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Montant dû"))
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name=_("Montant payé"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', verbose_name=_("Statut"))
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))

    class Meta:
        db_table = 'payment_schedule'
        verbose_name = _('Échéance de paiement')
        verbose_name_plural = _('Échéances de paiement')
        ordering = ['due_date']

    def __str__(self):
        return gettext("Échéance %(due_date)s – %(amount_due)s FCFA (%(status)s)") % {
            'due_date': self.due_date, 'amount_due': self.amount_due, 'status': self.get_status_display(),
        }

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

