"""
Serializers for sale-related endpoints.
Correspond à l'ancien endpoint Flask: POST /sale
"""

from rest_framework import serializers
from core.models import Product, Sale, SaleProduct, CreditSale, Client


# ── Lecture ────────────────────────────────────────────────────────────

class SaleProductSerializer(serializers.ModelSerializer):
    """Serializer pour un article de vente (lecture)."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = SaleProduct
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'quantity', 'unit_price', 'subtotal',
        ]

    def get_subtotal(self, obj):
        return float(obj.unit_price * obj.quantity)


class CreditSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditSale
        fields = ['amount_paid', 'amount_remaining', 'due_date', 'is_fully_paid']


class SaleSerializer(serializers.ModelSerializer):
    """Serializer complet de lecture pour une vente."""
    client_name = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    items = SaleProductSerializer(source='sale_products', many=True, read_only=True)
    credit_info = CreditSaleSerializer(read_only=True)

    class Meta:
        model = Sale
        fields = [
            'id', 'client_name', 'staff_name', 'total',
            'is_credit', 'is_paid', 'create_at', 'items', 'credit_info',
        ]

    def get_client_name(self, obj):
        if obj.client:
            return f"{obj.client.firstname} {obj.client.lastname}"
        return "Client de passage"

    def get_staff_name(self, obj):
        if obj.staff:
            return obj.staff.get_full_name()
        return "N/A"


# ── Écriture ──────────────────────────────────────────────────────────

class SaleItemCreateSerializer(serializers.Serializer):
    """Serializer pour un article dans une création de vente."""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate_product_id(self, value):
        try:
            Product.objects.get(id=value, delete_at__isnull=True)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Produit introuvable.")
        return value

    def validate(self, data):
        product = Product.objects.get(id=data['product_id'])
        if data['quantity'] > product.stock:
            raise serializers.ValidationError({
                'quantity': f"Stock insuffisant. Disponible : {product.stock}"
            })
        if product.max_salable_price and data['unit_price'] > product.max_salable_price:
            raise serializers.ValidationError({
                'unit_price': f"Prix trop élevé. Maximum : {product.max_salable_price}"
            })
        if (product.actual_price
                and data['unit_price'] < product.actual_price
                and not product.is_price_reducible):
            raise serializers.ValidationError({
                'unit_price': "Le prix de ce produit ne peut pas être réduit."
            })
        return data


class SaleCreateSerializer(serializers.Serializer):
    """
    Serializer pour créer une vente complète.
    Correspond à l'ancien endpoint Flask: POST /sale
    """
    client_id = serializers.IntegerField(required=False, allow_null=True)
    is_credit = serializers.BooleanField(default=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    payment_method = serializers.ChoiceField(
        choices=['CASH', 'MOBILE_MONEY', 'BANK_TRANSFER', 'CHECK'],
        default='CASH', required=False,
    )
    items = SaleItemCreateSerializer(many=True)

    # Alias accepté par l'ancienne app mobile
    sale_products = SaleItemCreateSerializer(many=True, required=False)

    def validate_client_id(self, value):
        if value:
            if not Client.objects.filter(id=value, delete_at__isnull=True).exists():
                raise serializers.ValidationError("Client introuvable.")
        return value

    def validate(self, data):
        # Accepter aussi le champ « sale_products » (compat ancien client)
        items = data.get('items') or data.pop('sale_products', [])
        data['items'] = items

        if not items:
            raise serializers.ValidationError({'items': "Au moins un article requis."})
        if data.get('is_credit') and not data.get('due_date'):
            raise serializers.ValidationError({
                'due_date': "Date d'échéance obligatoire pour une vente à crédit."
            })
        return data

