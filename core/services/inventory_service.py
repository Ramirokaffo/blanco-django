"""
Service pour la gestion des inventaires.
"""

from core.models import Inventory, Product
from core.services.excercise_service import ExerciseService


class InventoryService:

    @staticmethod
    def create_inventory(validated_data: dict, staff):
        """
        Crée un inventaire pour un produit.
        Correspond à l'ancien endpoint Flask: POST /create_inventory
        """
        product = Product.objects.get(id=validated_data['product_id'])
        exercise = ExerciseService.get_or_create_current_exercise()

        inventory = Inventory.objects.create(
            product=product,
            staff=staff,
            exercise=exercise,
            quantity_counted=validated_data['quantity_counted'],
            quantity_system=product.stock,
            difference=validated_data['quantity_counted'] - product.stock,
            notes=validated_data.get('notes', ''),
        )
        return inventory

