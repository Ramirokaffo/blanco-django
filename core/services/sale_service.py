"""
Service pour la gestion des ventes.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.models import (
    Sale, SaleProduct, SaleReturn, SaleReturnLine, CreditSale, Product, Client, Refund,
)
from core.models.inventory_models import PaymentSchedule
from core.models.settings_models import SystemSettings
from core.services.daily_service import DailyService
from core.services.accounting_service import AccountingService


class SaleService:

    @staticmethod
    def _append_note(existing_note, new_note):
        return f"{existing_note}\n{new_note}".strip() if existing_note else new_note

    @staticmethod
    def _adjust_credit_schedules(credit_sale, reduction_amount, reason=''):
        remaining_reduction = Decimal(str(reduction_amount or 0))
        if remaining_reduction <= 0:
            return

        schedules = list(
            PaymentSchedule.objects.select_for_update().filter(
                credit_sale=credit_sale,
                delete_at__isnull=True,
            ).order_by('due_date', 'id')
        )

        for schedule in schedules:
            if remaining_reduction <= 0:
                break

            current_due = Decimal(str(schedule.amount_due or 0))
            reduction = min(current_due, remaining_reduction)
            schedule.amount_due = current_due - reduction
            if schedule.amount_paid > schedule.amount_due:
                schedule.amount_paid = schedule.amount_due

            note = f"Retour partiel vente #{credit_sale.sale_id} : -{reduction:,.0f} FCFA"
            if reason:
                note = f"{note} — Motif: {reason}"
            schedule.notes = SaleService._append_note(schedule.notes, note)
            schedule.update_status()
            schedule.save(update_fields=['amount_due', 'amount_paid', 'status', 'notes'])
            remaining_reduction -= reduction

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
            has_vat=False,  # Sera mis à jour après
        )

        # Créer les articles et mettre à jour le stock
        has_vat = False
        for item_data in items_data:
            product = Product.objects.select_for_update().get(id=item_data['product_id'])
            if product.has_vat:
                has_vat = True
            SaleProduct.objects.create(
                sale=sale,
                product=product,
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
            )
            product.stock -= item_data['quantity']
            product.save(update_fields=['stock'])

        # Mettre à jour le champ has_vat sur la vente
        sale.has_vat = has_vat
        sale.save(update_fields=['has_vat'])

        # Récupérer les paramètres système
        settings = SystemSettings.get_settings()
        enable_tva = getattr(settings, 'enable_tva_accounting', True)
        tva_mode = getattr(settings, 'tva_accounting_mode', 'IMMEDIATE')

        # Déterminer s'il faut appliquer la TVA immédiatement
        apply_tax_now = enable_tva and has_vat and tva_mode == 'IMMEDIATE'

        # Créer le crédit si nécessaire
        if is_credit:
            credit_sale = CreditSale.objects.create(
                sale=sale,
                amount_paid=0,
                amount_remaining=total,
                due_date=due_date,
                is_fully_paid=False,
            )
            # Créer une échéance de paiement
            if due_date:
                PaymentSchedule.objects.create(
                    schedule_type='CLIENT',
                    credit_sale=credit_sale,
                    due_date=due_date,
                    amount_due=total,
                    status='PENDING',
                )

        # Enregistrer l'écriture comptable
        try:
            AccountingService.record_sale(
                sale=sale,
                daily=daily,
                exercise=daily.exercise,
                payment_method=payment_method,
                apply_tax=apply_tax_now,
            )
            # Marquer les écritures TVA comme créées si on est en mode immédiat
            if apply_tax_now:
                sale.tva_accounting_created = True
                sale.save(update_fields=['tva_accounting_created'])
        except Exception:
            pass  # Ne pas bloquer la vente si la comptabilité échoue

        return sale

    @staticmethod
    @transaction.atomic
    def cancel_sale(sale, reason='', refund_payment_method='CASH'):
        """Annule totalement une vente avec remise en stock et contrepassation."""
        cancel_at = timezone.now()
        sale = Sale.objects.select_for_update().select_related(
            'daily', 'daily__exercise', 'credit_info', 'invoice'
        ).prefetch_related('sale_products__product', 'credit_info__payments').get(id=sale.id)

        if sale.delete_at is not None:
            raise ValueError("Cette vente est déjà annulée.")

        sale_lines = list(sale.sale_products.filter(delete_at__isnull=True).select_related('product'))
        if not sale_lines:
            raise ValueError("Impossible d'annuler une vente sans lignes de produits actives.")

        credit_sale = getattr(sale, 'credit_info', None) if sale.is_credit else None
        amount_paid = Decimal('0')
        if credit_sale:
            amount_paid = Decimal(str(credit_sale.amount_paid or 0))

        refund_amount = amount_paid if sale.is_credit else Decimal(str(sale.total or 0))

        accounting_daily = DailyService.get_or_create_active_daily() or sale.daily
        exercise = accounting_daily.exercise if accounting_daily else sale.daily.exercise
        AccountingService.record_sale_cancellation(
            sale=sale,
            daily=accounting_daily,
            exercise=exercise,
            refund_payment_method=refund_payment_method,
            refund_amount=refund_amount,
        )

        for sale_product in sale_lines:
            product = Product.objects.select_for_update().get(id=sale_product.product_id)
            product.stock += sale_product.quantity
            product.save(update_fields=['stock'])

        if refund_amount > 0:
            Refund.objects.create(
                sale=sale,
                value=refund_amount,
                reason=reason or None,
            )

        invoice = getattr(sale, 'invoice', None)
        if invoice and invoice.delete_at is None and invoice.status != 'CANCELLED':
            note = f"Annulée le {timezone.localtime(cancel_at).strftime('%d/%m/%Y %H:%M')}"
            if reason:
                note = f"{note} — Motif: {reason}"
            invoice.status = 'CANCELLED'
            invoice.notes = f"{invoice.notes}\n{note}".strip() if invoice.notes else note
            invoice.save(update_fields=['status', 'notes'])

        if credit_sale and credit_sale.delete_at is None:
            credit_sale.delete_at = cancel_at
            credit_sale.save(update_fields=['delete_at'])
            PaymentSchedule.objects.filter(
                credit_sale=credit_sale,
                delete_at__isnull=True,
            ).update(delete_at=cancel_at)

        sale.delete_at = cancel_at
        sale.save(update_fields=['delete_at'])
        return refund_amount

    @staticmethod
    @transaction.atomic
    def partial_return_sale(sale, returned_items, reason='', refund_payment_method='CASH'):
        """Enregistre un retour partiel avec ajustement stock/compta/crédit."""
        return_at = timezone.now()
        sale = Sale.objects.select_for_update().select_related(
            'daily', 'daily__exercise', 'credit_info', 'invoice'
        ).prefetch_related('sale_products__product').get(id=sale.id)

        if sale.delete_at is not None:
            raise ValueError("Cette vente est déjà annulée.")
        if not returned_items:
            raise ValueError("Veuillez sélectionner au moins une quantité à retourner.")

        sale_products = {
            sp.id: sp
            for sp in sale.sale_products.filter(delete_at__isnull=True).select_related('product')
        }
        if not sale_products:
            raise ValueError("Impossible d'enregistrer un retour sur une vente sans lignes actives.")

        validated_items = []
        return_total = Decimal('0')
        remaining_quantity_exists = False

        for item in returned_items:
            sale_product_id = getattr(item.get('sale_product'), 'id', item.get('sale_product_id'))
            quantity = int(item.get('quantity') or 0)
            sale_product = sale_products.get(sale_product_id)

            if sale_product is None:
                raise ValueError("Une ligne de vente demandée est introuvable ou inactive.")
            if quantity <= 0:
                continue
            if quantity > sale_product.quantity:
                raise ValueError(f"La quantité retournée dépasse le disponible pour {sale_product.product.name}.")

            line_total = Decimal(str(sale_product.unit_price)) * quantity
            validated_items.append({
                'sale_product': sale_product,
                'quantity': quantity,
                'line_total': line_total,
            })
            return_total += line_total

        if not validated_items:
            raise ValueError("Veuillez sélectionner au moins une quantité à retourner.")

        for sale_product in sale_products.values():
            requested_qty = next(
                (item['quantity'] for item in validated_items if item['sale_product'].id == sale_product.id),
                0,
            )
            if sale_product.quantity - requested_qty > 0:
                remaining_quantity_exists = True
                break

        if not remaining_quantity_exists:
            raise ValueError("Ce retour couvre toute la vente. Utilisez l'annulation totale pour ce cas.")

        previous_total = Decimal(str(sale.total or 0))
        new_total = previous_total - return_total
        if new_total <= 0:
            raise ValueError("Ce retour couvre toute la vente. Utilisez l'annulation totale pour ce cas.")

        sale_return = SaleReturn.objects.create(
            sale=sale,
            total=return_total,
            reason=reason or None,
        )

        for item in validated_items:
            sale_product = item['sale_product']
            quantity = item['quantity']
            product = Product.objects.select_for_update().get(id=sale_product.product_id)
            product.stock += quantity
            product.save(update_fields=['stock'])

            SaleReturnLine.objects.create(
                sale_return=sale_return,
                sale_product=sale_product,
                quantity=quantity,
                unit_price=sale_product.unit_price,
            )

            remaining_qty = sale_product.quantity - quantity
            sale_product.quantity = remaining_qty
            update_fields = ['quantity']
            if remaining_qty <= 0:
                sale_product.quantity = 0
                sale_product.delete_at = return_at
                update_fields.append('delete_at')
            sale_product.save(update_fields=update_fields)

        refund_amount = Decimal('0')
        credit_sale = getattr(sale, 'credit_info', None) if sale.is_credit else None
        if sale.is_credit:
            if credit_sale is None or credit_sale.delete_at is not None:
                raise ValueError("La vente à crédit ne possède pas d'information de crédit active.")

            current_paid = Decimal(str(credit_sale.amount_paid or 0))
            refund_amount = max(current_paid - new_total, Decimal('0'))
            credit_sale.amount_paid = current_paid - refund_amount
            credit_sale.amount_remaining = max(new_total - credit_sale.amount_paid, Decimal('0'))
            credit_sale.is_fully_paid = credit_sale.amount_remaining <= 0
            sale.is_paid = credit_sale.is_fully_paid
            credit_sale.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])
            SaleService._adjust_credit_schedules(credit_sale, return_total, reason=reason)
        else:
            refund_amount = return_total
            sale.is_paid = True

        sale.total = new_total
        sale.save(update_fields=['total', 'is_paid'])

        accounting_daily = DailyService.get_or_create_active_daily() or sale.daily
        exercise = accounting_daily.exercise if accounting_daily else sale.daily.exercise
        AccountingService.record_partial_sale_return(
            sale=sale,
            amount=return_total,
            daily=accounting_daily,
            exercise=exercise,
            refund_payment_method=refund_payment_method,
            refund_amount=refund_amount,
        )

        if refund_amount > 0:
            refund_reason = reason or 'Retour partiel'
            Refund.objects.create(
                sale=sale,
                value=refund_amount,
                reason=f"Retour partiel — {refund_reason}",
            )

        invoice = getattr(sale, 'invoice', None)
        if invoice and invoice.delete_at is None:
            note = (
                f"Retour partiel le {timezone.localtime(return_at).strftime('%d/%m/%Y %H:%M')} "
                f"— Montant retourné: {return_total:,.0f} FCFA"
            )
            if refund_amount > 0:
                note = f"{note} — Remboursement: {refund_amount:,.0f} FCFA"
            if reason:
                note = f"{note} — Motif: {reason}"
            invoice.notes = SaleService._append_note(invoice.notes, note)
            invoice.save(update_fields=['notes'])

        return sale_return, refund_amount

