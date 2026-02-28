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
    code = models.CharField(max_length=255, unique=True, verbose_name="Code", help_text="Code du produit")
    name = models.CharField(max_length=255, verbose_name="Nom", help_text="Nom du produit")
    description = models.TextField(null=True, blank=True, verbose_name="Description", help_text="Description du produit")
    brand = models.CharField(max_length=255, null=True, blank=True, verbose_name="Marque", help_text="Marque du produit")
    color = models.CharField(max_length=100, null=True, blank=True, verbose_name="Couleur", help_text="Couleur du produit")
    stock = models.IntegerField(default=0, verbose_name="Stock", help_text="Stock actuel du produit")
    stock_limit = models.IntegerField(null=True, blank=True, verbose_name="Seuil d'alerte de stock", help_text="Seuil d'alerte de stock")
    max_salable_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Prix maximum autorisé pour la vente", help_text="Prix maximum autorisé pour la vente")
    last_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Dernier prix d'achat", help_text="Dernier prix d'achat du produit")
    actual_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Prix actuel du produit", help_text="Prix actuel du produit")
    exp_alert_period = models.IntegerField(null=True, blank=True, verbose_name="Période d'alerte d'expiration (jours)", help_text="Période d'alerte d'expiration (jours)")
    grammage = models.FloatField(null=True, blank=True, verbose_name="Grammage", help_text="Grammage du produit")
    is_price_reducible = models.BooleanField(default=True, verbose_name="Prix réductible?", help_text="Indique si le prix du produit peut être réduit")
    has_vat = models.BooleanField(default=True, verbose_name="TVA applicable?", help_text="Indique si le produit est soumis à la TVA")
    
    # Foreign Keys
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Catégorie", related_name='products', help_text="Catégorie du produit")
    gamme = models.ForeignKey(Gamme, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Gamme", related_name='products', help_text="Gamme du produit")
    grammage_type = models.ForeignKey(GrammageType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Type de grammage", related_name='products', help_text="Type de grammage du produit")
    rayon = models.ForeignKey(Rayon, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Rayon", related_name='products', help_text="Rayon du produit")
    
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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="Produit associé", related_name='images', help_text="Produit associé")
    image_path = models.CharField(max_length=500, verbose_name="Chemin de l'image", help_text="Chemin de l'image")
    is_primary = models.BooleanField(default=False, verbose_name="Image principale", help_text="Indique si l'image est la principale")
    
    class Meta:
        db_table = 'product_image'
        # managed = False
        verbose_name = 'Image produit'
        verbose_name_plural = 'Images produits'
    
    def __str__(self):
        return f"Image pour {self.product.name}"

