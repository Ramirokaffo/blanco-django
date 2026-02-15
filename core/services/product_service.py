"""
Service pour la gestion des produits.
"""

import os
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from core.models import (
    Product, ProductImage, Supply, Inventory,
    Category, Gamme, Rayon, GrammageType,
)


class ProductService:

    # ── Lecture ────────────────────────────────────────────────────────

    @staticmethod
    def get_product_list(page: int = 1, count: int = 20):
        """Liste paginée de produits actifs."""
        offset = (page - 1) * count
        return Product.objects.filter(
            delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        ).prefetch_related('images')[offset:offset + count]

    @staticmethod
    def search_products(search_input: str, page: int = 1, count: int = 20):
        """Recherche de produits par nom ou code."""
        offset = (page - 1) * count
        return Product.objects.filter(
            Q(name__icontains=search_input) | Q(code__icontains=search_input),
            delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        )[offset:offset + count]

    @staticmethod
    def get_by_id(product_id: int):
        """Récupère un produit avec toutes ses relations."""
        return Product.objects.filter(
            id=product_id, delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        ).prefetch_related('images').first()

    @staticmethod
    def get_by_code(product_code: str):
        """Récupère un produit par son code."""
        return Product.objects.filter(
            code=product_code, delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        ).prefetch_related('images').first()

    @staticmethod
    def get_by_name(product_name: str):
        """Récupère un produit par son nom (recherche exacte insensible à la casse)."""
        return Product.objects.filter(
            name__iexact=product_name, delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        ).prefetch_related('images').first()

    # ── Écriture ──────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_product(validated_data: dict, images: list, staff, daily):
        """
        Crée un produit, ses images et l'approvisionnement initial.
        Correspond à l'ancien endpoint Flask: POST /create_product
        """
        image_files = validated_data.pop('images', [])
        stock = validated_data.pop('stock', 0)
        unit_price = validated_data.pop('unit_price', 0)

        # 1. Créer le produit
        product = Product.objects.create(stock=stock, **validated_data)

        # 2. Sauvegarder les images
        image_dir = os.path.join(settings.MEDIA_ROOT, 'product')
        os.makedirs(image_dir, exist_ok=True)

        for i, img_file in enumerate(images):
            is_primary = (i == 0)
            file_name = img_file.name
            file_path = os.path.join(image_dir, file_name)
            with open(file_path, 'wb+') as dest:
                for chunk in img_file.chunks():
                    dest.write(chunk)
            ProductImage.objects.create(
                product=product,
                image_path=file_name,
                is_primary=is_primary,
            )

        # 3. Créer l'approvisionnement initial
        if stock > 0 and daily:
            Supply.objects.create(
                product=product,
                staff=staff,
                daily=daily,
                quantity=stock,
                unit_price=unit_price or 0,
                total_price=(unit_price or 0) * stock,
            )

        return product

    # ── Image helper ──────────────────────────────────────────────────

    @staticmethod
    def get_image_path(folder: str, filename: str) -> str:
        """Retourne le chemin absolu d'une image si elle existe."""
        path = os.path.join(settings.MEDIA_ROOT, folder, filename)
        return path if os.path.isfile(path) else None

