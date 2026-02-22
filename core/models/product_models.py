"""
Product-related models: Category, Gamme, Rayon, GrammageType, Product, ProductImage.
"""

from django.db import models
from .base_models import SoftDeleteModel


class Category(SoftDeleteModel):
    """
    Product category model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'category'
        # managed = False
        verbose_name = 'Catégorie'
        verbose_name_plural = 'Catégories'
    
    def __str__(self):
        return self.name


class Gamme(SoftDeleteModel):
    """
    Product range/line model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'gamme'
        # managed = False
        verbose_name = 'Gamme produit'
        verbose_name_plural = 'Gammes produits'
    
    def __str__(self):
        return self.name


class Rayon(SoftDeleteModel):
    """
    Product department/section model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'rayon'
        # managed = False
        verbose_name = 'Rayon produit'
        verbose_name_plural = 'Rayons produits'
    
    def __str__(self):
        return self.name


class GrammageType(SoftDeleteModel):
    """
    Grammage/Weight type model (e.g., kg, g, L, ml).
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'grammage_type'
        # managed = False
        verbose_name = 'Type de grammage'
        verbose_name_plural = 'Types de grammage'
    
    def __str__(self):
        return self.name


class Product(SoftDeleteModel):
    """
    Main product model.
    """
    code = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    brand = models.CharField(max_length=255, null=True, blank=True)
    color = models.CharField(max_length=100, null=True, blank=True)
    stock = models.IntegerField(default=0)
    stock_limit = models.IntegerField(null=True, blank=True)
    max_salable_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    actual_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    last_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    exp_alert_period = models.IntegerField(null=True, blank=True, help_text="Expiration alert period in days")
    grammage = models.FloatField(null=True, blank=True)
    is_price_reducible = models.BooleanField(default=True)
    
    # Foreign Keys
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    gamme = models.ForeignKey(Gamme, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    grammage_type = models.ForeignKey(GrammageType, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    rayon = models.ForeignKey(Rayon, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    
    class Meta:
        db_table = 'product'
        # managed = False
        verbose_name = 'Produit'
        verbose_name_plural = 'Produits'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def is_low_stock(self):
        """Check if product stock is below the limit."""
        if self.stock_limit:
            return self.stock <= self.stock_limit
        return False


class ProductImage(SoftDeleteModel):
    """
    Product images model.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image_path = models.CharField(max_length=500)
    is_primary = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'product_image'
        # managed = False
        verbose_name = 'Image produit'
        verbose_name_plural = 'Images produits'
    
    def __str__(self):
        return f"Image pour {self.product.name}"

