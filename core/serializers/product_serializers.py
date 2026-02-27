"""
Serializers for product-related endpoints.
Correspond aux anciens endpoints Flask:
  - GET /get_product_list/<page>/<count>
  - GET /search_product
  - GET /get_product_by_id/<product_id>
  - GET /get_product_by_code/<product_code>
  - GET /get_product_by_name/<product_name>
  - GET /get_category, /get_rayon, /get_gamme, /get_grammage_type
  - POST /create_product
"""

from rest_framework import serializers
from core.models import (
    Product, ProductImage, Category, Gamme, Rayon, GrammageType,
)


# ── Serializers de référence (lookup tables) ──────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']


class GammeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gamme
        fields = ['id', 'name', 'description']


class RayonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rayon
        fields = ['id', 'name', 'description']


class GrammageTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrammageType
        fields = ['id', 'name', 'description']


# ── ProductImage ──────────────────────────────────────────────────────

class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ['id', 'image_path', 'is_primary', 'url']

    def get_url(self, obj):
        request = self.context.get('request')
        if obj.image_path and request:
            return request.build_absolute_uri(f'/api/images/product/{obj.image_path}')
        return None


# ── Product : lecture ─────────────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes paginées de produits."""

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'name', 'stock', 'max_salable_price',
            'actual_price', 'is_price_reducible',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['available'] = instance.stock > 0
        return data


# Alias pour garder la compatibilité avec le code existant
ProductSearchSerializer = ProductListSerializer


class ProductDetailSerializer(serializers.ModelSerializer):
    """Serializer complet pour le détail d'un produit."""
    category = CategorySerializer(read_only=True)
    gamme = GammeSerializer(read_only=True)
    rayon = RayonSerializer(read_only=True)
    grammage_type = GrammageTypeSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'name', 'description', 'brand', 'color',
            'stock', 'stock_limit', 'max_salable_price', 'actual_price',
            'is_price_reducible', 'grammage', 'exp_alert_period',
            'category', 'gamme', 'rayon', 'grammage_type',
            'images', 'create_at', 'delete_at',
        ]


# ── Product : écriture ────────────────────────────────────────────────

class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer pour créer un produit.
    Correspond à l'ancien endpoint Flask: POST /create_product
    """
    stock = serializers.IntegerField(required=False, default=0)
    images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False,
    )

    class Meta:
        model = Product
        fields = [
            'code', 'name', 'description', 'brand', 'color',
            'stock', 'stock_limit', 'max_salable_price', 'actual_price',
            'is_price_reducible', 'grammage', 'exp_alert_period',
            'category', 'gamme', 'rayon', 'grammage_type',
            'images', 'last_purchase_price'
        ]

    def validate_code(self, value):
        if Product.objects.filter(code=value).exists():
            raise serializers.ValidationError("Ce code produit existe déjà.")
        return value


class ProductUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour mettre à jour un produit.
    Nouveau endpoint: PATCH /api/products/by-code/<product_code>/update
    """
    code = serializers.CharField(required=False)
    images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False,
    )

    class Meta:
        model = Product
        fields = [
            'code', 'name', 'description', 'brand', 'color',
            'stock', 'stock_limit', 'max_salable_price', 'actual_price',
            'is_price_reducible', 'grammage', 'exp_alert_period',
            'category', 'gamme', 'rayon', 'grammage_type',
            'images', 'last_purchase_price',
        ]
        extra_kwargs = {
            'code': {'required': False},
            'name': {'required': False},
        }

    def validate_code(self, value):
        # Vérifier que le code n'existe pas déjà (sauf pour le produit actuel)
        instance = self.instance
        if instance and Product.objects.filter(code=value).exclude(id=instance.id).exists():
            raise serializers.ValidationError("Ce code produit existe déjà.")
        elif not instance and Product.objects.filter(code=value).exists():
            raise serializers.ValidationError("Ce code produit existe déjà.")
        return value

