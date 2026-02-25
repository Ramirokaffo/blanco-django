"""
Service pour la gestion des ventes.
"""

from django.db import transaction
from django.db.models import Q

from core.models import (
    Sale, SaleProduct, CreditSale, Product, Client, Daily,
)
from core.services.daily_service import DailyService
from core.services.accounting_service import AccountingService


class SaleService:

    # ── Lecture ────────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(sale_id: int):
        """Récupère une vente par son ID."""
        return Sale.objects.filter(
            id=sale_id, delete_at__isnull=True,
        ).select_related('client', 'staff', 'daily').first()

    @staticmethod
    def search_sales(query: str = ''):
        """Recherche de ventes dans le Daily en cours."""
        current_daily = DailyService.get_or_create_active_daily()
        if not current_daily:
            return Sale.objects.none()

        qs = Sale.objects.select_related('client', 'staff', 'daily').filter(
            delete_at__isnull=True, daily=current_daily,
        )
        if query:
            qs = qs.filter(
                Q(client__firstname__icontains=query)
                | Q(client__lastname__icontains=query)
                | Q(staff__first_name__icontains=query)
                | Q(staff__last_name__icontains=query)
                | Q(total__icontains=query)
                | Q(id__icontains=query)
                | Q(sale_products__product__name__icontains=query)
                | Q(sale_products__product__code__icontains=query)
            ).distinct()
        return qs.order_by('-create_at')

    # ── Écriture ──────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_sale(validated_data: dict, staff):
        """
        Crée une vente complète (vente, articles, crédit éventuel).
        Correspond à l'ancien endpoint Flask: POST /sale
        """
        items_data = validated_data.pop('items')
        client_id = validated_data.pop('client_id', None)
        is_credit = validated_data.get('is_credit', False)
        due_date = validated_data.get('due_date')
        payment_method = validated_data.pop('payment_method', 'CASH')

        client = Client.objects.get(id=client_id) if client_id else None
        daily = DailyService.get_or_create_active_daily()
        if not daily:
            raise ValueError("Aucune session Daily ouverte.")

        # Calculer le total
        total = sum(
            item['unit_price'] * item['quantity']
            for item in items_data
        )

        # Créer la vente
        sale = Sale.objects.create(
            client=client,
            staff=staff,
            daily=daily,
            total=total,
            is_credit=is_credit,
            is_paid=not is_credit,
        )

        # Créer les articles et mettre à jour le stock
        for item_data in items_data:
            product = Product.objects.select_for_update().get(id=item_data['product_id'])
            SaleProduct.objects.create(
                sale=sale,
                product=product,
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
            )
            product.stock -= item_data['quantity']
            product.save(update_fields=['stock'])

        # Créer le crédit si nécessaire
        if is_credit:
            CreditSale.objects.create(
                sale=sale,
                amount_paid=0,
                amount_remaining=total,
                due_date=due_date,
                is_fully_paid=False,
            )

        # Enregistrer l'écriture comptable
        try:
            AccountingService.record_sale(
                sale=sale,
                daily=daily,
                exercise=daily.exercise,
                payment_method=payment_method,
            )
        except Exception:
            pass  # Ne pas bloquer la vente si la comptabilité échoue

        return sale

