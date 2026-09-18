"""
Sale-related models: Sale, SaleProduct, SaleReturn, SaleReturnLine, CreditSale, Refund.
"""

from django.db import models
from django.utils.translation import gettext, gettext_lazy as _
from django.conf import settings

from core.models.base_models import SoftDeleteModel


class Sale(SoftDeleteModel):
    """
    Sale/Transaction model.
    """
    is_paid = models.BooleanField(default=False)
    is_credit = models.BooleanField(default=False)
    total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    client = models.ForeignKey('Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    daily = models.ForeignKey('Daily', on_delete=models.CASCADE, related_name='sales')
    
    # Champs pour le suivi de la comptabilité TVA
    has_vat = models.BooleanField(
        default=False,
        verbose_name=_("TVA applicable"),
        help_text=_("Indique si la vente contient des produits avec TVA")
    )
    tva_accounting_created = models.BooleanField(
        default=False,
        verbose_name=_("Écritures TVA créées"),
        help_text=_("Indique si les écritures comptables de TVA ont déjà été créées")
    )
    accounting_pending = models.BooleanField(
        default=False,
        verbose_name=_("Écriture comptable en attente"),
        help_text=_(
            "Vrai si l'écriture comptable de la vente a échoué et doit être "
            "rejouée (commande replay_accounting)."
        ),
    )
    
    class Meta:
        db_table = 'sale'
        # managed = False
        verbose_name = _('Vente')
        verbose_name_plural = _('Ventes')
        ordering = ['-create_at']
    
    def __str__(self):
        return gettext("Vente #%(id)s - %(total)s FCFA") % {'id': self.id, 'total': self.total}
    
    def get_total(self):
        """Calculate total from sale products."""
        return sum(
            sp.get_subtotal()
            for sp in self.sale_products.filter(delete_at__isnull=True, quantity__gt=0)
        )
    
    def get_related_credit_sale(self):
        """Get related CreditSale if exists."""
        try:
            return CreditSale.objects.get(sale=self)
        except CreditSale.DoesNotExist:
            return None


class SaleProduct(SoftDeleteModel):
    """
    Sale-Product relationship model (items in a sale).
    """
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='sale_products')
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='sale_products')
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    class Meta:
        db_table = 'sale_product'
        # managed = False
        verbose_name = _('Produit vendu')
        verbose_name_plural = _('Produits vendus')
    
    def __str__(self):
        return f"{self.product.name} x{self.quantity}"
    
    def get_subtotal(self):
        """Calculate subtotal for this line item."""
        subtotal = self.quantity * self.unit_price
        return subtotal


class SaleReturn(SoftDeleteModel):
    """Trace d'un retour partiel de vente."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='sale_returns')
    total = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'sale_return'
        verbose_name = _('Retour de vente')
        verbose_name_plural = _('Retours de vente')
        ordering = ['-create_at']

    def __str__(self):
        return gettext("Retour %(total)s pour Vente #%(sale_id)s") % {'total': self.total, 'sale_id': self.sale_id}


class SaleReturnLine(SoftDeleteModel):
    """Ligne d'un retour partiel, avec snapshot quantité/prix."""

    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name='lines')
    sale_product = models.ForeignKey(SaleProduct, on_delete=models.CASCADE, related_name='return_lines')
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'sale_return_line'
        verbose_name = _('Ligne de retour de vente')
        verbose_name_plural = _('Lignes de retour de vente')

    def __str__(self):
        return gettext("Retour ligne vente #%(sale_id)s - x%(quantity)s") % {'sale_id': self.sale_return.sale_id, 'quantity': self.quantity}

    def get_subtotal(self):
        return self.quantity * self.unit_price


class CreditSale(SoftDeleteModel):
    """
    Credit sale model for tracking sales on credit.
    """
    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name='credit_info')
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    is_fully_paid = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'credit_sale'
        # managed = False
        verbose_name = _('Vente crédit')
        verbose_name_plural = _('Ventes crédit')
    
    def __str__(self):
        return gettext("Vente crédit #%(sale_id)s") % {'sale_id': self.sale.id}
    
    def get_remaining_balance(self):
        """Calculate remaining balance."""
        return self.sale.total - self.amount_paid if self.sale.total else 0


class Refund(SoftDeleteModel):
    """
    Refund model for tracking refunds.
    """
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='refunds')
    value = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'refund'
        # managed = False
        verbose_name = _('Remboursement')
        verbose_name_plural = _('Remboursements')
    
    def __str__(self):
        return gettext("Remboursement %(value)s pour Vente #%(sale_id)s") % {'value': self.value, 'sale_id': self.sale.id}

