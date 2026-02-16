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
            valid_product_count=validated_data['valid_product_count'],
            invalid_product_count=validated_data.get('invalid_product_count', 0),
            notes=validated_data.get('notes', ''),
        )
        return inventory

