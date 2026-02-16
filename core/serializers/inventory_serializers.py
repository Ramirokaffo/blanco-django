"""
Serializers for inventory-related endpoints.
Correspond à l'ancien endpoint Flask: POST /create_inventory
"""

from rest_framework import serializers
from core.models import Inventory, Product


class InventorySerializer(serializers.ModelSerializer):
    """Serializer de lecture pour un inventaire."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    staff_name = serializers.SerializerMethodField()

    class Meta:
        model = Inventory
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'staff_name', 'exercise',
            'valid_product_count', 'invalid_product_count',
            'is_close', 'notes', 'create_at',
        ]

    def get_staff_name(self, obj):
        if obj.staff:
            return obj.staff.get_full_name()
        return "N/A"


class InventoryCreateSerializer(serializers.Serializer):
    """
    Serializer pour créer un inventaire.
    Correspond à l'ancien endpoint Flask: POST /create_inventory
    Champs attendus :
        { "product_id": int, "valid_product_count": int, "invalid_product_count": int, "notes": str|null }
    """
    product_id = serializers.IntegerField()
    valid_product_count = serializers.IntegerField(min_value=0)
    invalid_product_count = serializers.IntegerField(min_value=0, required=False, default=0)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_product_id(self, value):
        if not Product.objects.filter(id=value, delete_at__isnull=True).exists():
            raise serializers.ValidationError("Produit introuvable.")
        return value

