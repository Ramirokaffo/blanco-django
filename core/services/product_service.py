"""
Service pour la gestion des produits.
"""

import os
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from django.db.models import Q
from django.utils._os import safe_join
from django.utils.translation import gettext as _

from core.models import (
    Product, ProductImage, Supply, Inventory,
    Category, Gamme, Rayon, GrammageType,
)


class ProductService:

    # ── Lecture ────────────────────────────────────────────────────────

    @staticmethod
    def get_product_list(page: int = 1, count: int = 20):
        """Liste paginée de produits actifs."""
        offset = (page) * count
        return Product.objects.filter(
            delete_at__isnull=True,
        ).select_related(
            'category', 'gamme', 'rayon', 'grammage_type',
        ).prefetch_related('images')[offset:offset + count]

    @staticmethod
    def search_products(search_input: str, page: int = 1, count: int = 20):
        """Recherche de produits par nom ou code."""
        offset = (page) * count
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
        stock = validated_data.pop('stock', 0) or 0
        unit_price = validated_data.pop('actual_price', None)
        last_purchase_price = validated_data.pop('last_purchase_price', 0)

        if stock < 0:
            raise ValueError(_("Le stock initial ne peut pas être négatif."))

        # 1. Créer le produit (actual_price reste renseigné sur le produit)
        product = Product.objects.create(
            stock=stock, actual_price=unit_price, **validated_data,
        )

        # 2. Sauvegarder les images (Django gère la sauvegarde automatiquement avec ImageField)
        for i, img_file in enumerate(images):
            is_primary = (i == 0)
            ProductImage.objects.create(
                product=product,
                image=img_file,
                is_primary=is_primary,
            )

        # 3. Créer l'approvisionnement initial, valorisé au prix d'ACHAT
        #    (et non au prix de vente) pour ne pas fausser les marges.
        purchase_cost = last_purchase_price or 0
        if stock > 0 and daily:
            Supply.objects.create(
                product=product,
                staff=staff,
                daily=daily,
                quantity=stock,
                purchase_cost=purchase_cost,
                total_price=purchase_cost * stock,
            )
        # Mettre à jour le dernier prix d'achat
        product.last_purchase_price = purchase_cost
        product.save(update_fields=['last_purchase_price'])

        return product

    @staticmethod
    @transaction.atomic
    def update_product(product: Product, validated_data: dict, images: list = None):
        """
        Met à jour un produit et ses images.
        Nouveau endpoint: PATCH /api/products/by-code/<product_code>/update
        """
        # Retirer les images du validated_data si présentes
        validated_data.pop('images', None)
        # Le stock ne se modifie jamais par cette voie (approvisionnement /
        # inventaire uniquement), même si un appelant l'a laissé passer.
        validated_data.pop('stock', None)

        # Verrouiller la ligne : une vente concurrente peut décrémenter le stock
        product = Product.objects.select_for_update().get(pk=product.pk)

        # Mettre à jour les champs du produit
        for field, value in validated_data.items():
            setattr(product, field, value)
        product.save(update_fields=list(validated_data.keys()) or None)

        # Sauvegarder les nouvelles images si fournies (Django gère la sauvegarde automatiquement avec ImageField)
        if images:
            for i, img_file in enumerate(images):
                # Si c'est la première image et qu'il n'y a pas d'image primaire, la marquer comme primaire
                is_primary = (i == 0 and not product.images.filter(is_primary=True).exists())
                ProductImage.objects.create(
                    product=product,
                    image=img_file,
                    is_primary=is_primary,
                )

        return product

    # ── Image helper ──────────────────────────────────────────────────

    # Dossiers de MEDIA_ROOT servis publiquement par /api/images/<folder>/<image>/
    PUBLIC_IMAGE_FOLDERS = ('product',)

    @staticmethod
    def get_image_path(folder: str, filename: str):
        """
        Retourne le chemin absolu d'une image publique si elle existe, sinon None.
        Le chemin est confiné à MEDIA_ROOT/<dossier autorisé>/ : toute tentative
        de traversée (``..``, chemin absolu, séparateurs) renvoie None.
        """
        if folder not in ProductService.PUBLIC_IMAGE_FOLDERS:
            return None
        if not filename or filename in ('.', '..') or '/' in filename or '\\' in filename:
            return None
        try:
            base = safe_join(settings.MEDIA_ROOT, folder)
            path = safe_join(base, filename)
        except (SuspiciousFileOperation, ValueError):
            return None
        return path if os.path.isfile(path) else None

