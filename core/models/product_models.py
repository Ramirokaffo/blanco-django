"""
Product-related models: Category, Gamme, Rayon, GrammageType, Product, ProductImage.
"""

from django.db import models
from django.utils.translation import gettext, gettext_lazy as _
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
        verbose_name = _('Catégorie')
        verbose_name_plural = _('Catégories')
    
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
        verbose_name = _('Gamme produit')
        verbose_name_plural = _('Gammes produits')
    
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
        verbose_name = _('Rayon produit')
        verbose_name_plural = _('Rayons produits')
    
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
        verbose_name = _('Type de grammage')
        verbose_name_plural = _('Types de grammage')
    
    def __str__(self):
        return self.name


class Product(SoftDeleteModel):
    """
    Main product model.
    """
    code = models.CharField(max_length=255, unique=True, verbose_name=_("Code"), help_text=_("Code du produit"))
    name = models.CharField(max_length=255, verbose_name=_("Nom"), help_text=_("Nom du produit"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"), help_text=_("Description du produit"))
    brand = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Marque"), help_text=_("Marque du produit"))
    color = models.CharField(max_length=100, null=True, blank=True, verbose_name=_("Couleur"), help_text=_("Couleur du produit"))
    stock = models.IntegerField(default=0, verbose_name=_("Stock"), help_text=_("Stock actuel du produit"))
    stock_limit = models.IntegerField(null=True, blank=True, verbose_name=_("Seuil d'alerte de stock"), help_text=_("Seuil d'alerte de stock"))
    max_salable_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_("Prix maximum autorisé pour la vente"), help_text=_("Prix maximum autorisé pour la vente"))
    min_salable_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_("Prix minimum autorisé pour la vente"), help_text=_("Prix minimum autorisé pour la vente"))
    last_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_("Prix d'achat"), help_text=_("Dernier prix d'achat du produit"))
    actual_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_("Prix actuel du produit"), help_text=_("Prix actuel du produit"))
    exp_alert_period = models.IntegerField(null=True, blank=True, verbose_name=_("Période d'alerte d'expiration (jours)"), help_text=_("Période d'alerte d'expiration (jours)"))
    grammage = models.FloatField(null=True, blank=True, verbose_name=_("Grammage"), help_text=_("Grammage du produit"))
    is_price_reducible = models.BooleanField(default=True, verbose_name=_("Prix réductible?"), help_text=_("Indique si le prix du produit peut être réduit"))
    has_vat = models.BooleanField(default=True, verbose_name=_("TVA applicable?"), help_text=_("Indique si le produit est soumis à la TVA"))
    
    # Foreign Keys
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Catégorie"), related_name='products', help_text=_("Catégorie du produit"))
    gamme = models.ForeignKey(Gamme, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Gamme"), related_name='products', help_text=_("Gamme du produit"))
    grammage_type = models.ForeignKey(GrammageType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Type de grammage"), related_name='products', help_text=_("Type de grammage du produit"))
    rayon = models.ForeignKey(Rayon, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Rayon"), related_name='products', help_text=_("Rayon du produit"))
    
    class Meta:
        db_table = 'product'
        # managed = False
        verbose_name = _('Produit')
        verbose_name_plural = _('Produits')
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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name=_("Produit associé"), related_name='images', help_text=_("Produit associé"))
    image = models.ImageField(upload_to='product/', null=True, verbose_name=_("Image du produit"), help_text=_("Fichier image du produit"))
    is_primary = models.BooleanField(default=False, verbose_name=_("Image principale"), help_text=_("Indique si l'image est la principale"))
    
    class Meta:
        db_table = 'product_image'
        # managed = False
        verbose_name = _('Image produit')
        verbose_name_plural = _('Images produits')
    
    def __str__(self):
        return gettext("Image pour %(product)s") % {'product': self.product.name}

