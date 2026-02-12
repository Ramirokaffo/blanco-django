"""
Sale-related models: Sale, SaleProduct, CreditSale, Refund.
"""

from django.db import models
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
    
    class Meta:
        db_table = 'sale'
        # managed = False
        verbose_name = 'Sale'
        verbose_name_plural = 'Sales'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Sale #{self.id} - {self.total} FCFA"
    
    def get_total(self):
        """Calculate total from sale products."""
        return sum(sp.get_subtotal() for sp in self.sale_products.all())
    
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
        verbose_name = 'Sale Product'
        verbose_name_plural = 'Sale Products'
    
    def __str__(self):
        return f"{self.product.name} x{self.quantity}"
    
    def get_subtotal(self):
        """Calculate subtotal for this line item."""
        subtotal = self.quantity * self.unit_price
        return subtotal


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
        verbose_name = 'Credit Sale'
        verbose_name_plural = 'Credit Sales'
    
    def __str__(self):
        return f"Credit for Sale #{self.sale.id}"
    
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
        verbose_name = 'Refund'
        verbose_name_plural = 'Refunds'
    
    def __str__(self):
        return f"Refund {self.value} for Sale #{self.sale.id}"

