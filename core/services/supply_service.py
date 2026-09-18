from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import Product, Supply, SupplyReturn
from core.models.inventory_models import CreditSupply, PaymentSchedule
from core.services.accounting_service import AccountingService
from core.services.daily_service import DailyService


class SupplyService:
    @staticmethod
    def _append_note(existing_note, new_note):
        return f"{existing_note}\n{new_note}".strip() if existing_note else new_note

    @staticmethod
    def _get_credit_supply(supply):
        if not getattr(supply, 'is_credit', False):
            return None
        try:
            return supply.credit_info
        except CreditSupply.DoesNotExist:
            return None

    @staticmethod
    def _adjust_credit_schedules(credit_supply, reduction_amount, reason=''):
        remaining_reduction = Decimal(str(reduction_amount or 0))
        if remaining_reduction <= 0:
            return

        schedules = list(
            PaymentSchedule.objects.select_for_update().filter(
                credit_supply=credit_supply,
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

            note = _("Retour partiel approvisionnement #%(id)s : -%(amount)s FCFA") % {
                'id': credit_supply.supply_id, 'amount': format(reduction, ',.0f'),
            }
            if reason:
                note = _("%(note)s — Motif: %(reason)s") % {'note': note, 'reason': reason}
            schedule.notes = SupplyService._append_note(schedule.notes, note)
            schedule.update_status()
            schedule.save(update_fields=['amount_due', 'amount_paid', 'status', 'notes'])
            remaining_reduction -= reduction

    @staticmethod
    def _ensure_exercise_open(supply):
        """Un approvisionnement d'un exercice clôturé ne peut plus être annulé ni retourné."""
        exercise = getattr(getattr(supply, 'daily', None), 'exercise', None)
        if exercise is not None and exercise.end_date is not None:
            raise ValueError(_(
                "Impossible de modifier un approvisionnement d'un exercice clôturé. "
                "Passez une écriture de régularisation dans l'exercice en cours."
            ))

    @staticmethod
    @transaction.atomic
    def cancel_supply(supply, reason='', refund_payment_method='CASH'):
        cancel_at = timezone.now()
        supply = Supply.objects.select_for_update().select_related(
            'product', 'supplier', 'daily', 'daily__exercise', 'credit_info', 'tax_rate'
        ).get(id=supply.id)

        if supply.delete_at is not None:
            raise ValueError(_("Cet approvisionnement est déjà annulé."))
        SupplyService._ensure_exercise_open(supply)

        product = Product.objects.select_for_update().get(id=supply.product_id)
        if (product.stock or 0) < supply.quantity:
            raise ValueError(_(
                "Stock insuffisant pour annuler cet approvisionnement et retourner la marchandise au fournisseur."
            ))

        credit_supply = SupplyService._get_credit_supply(supply)
        amount_paid = Decimal('0')
        if credit_supply and credit_supply.delete_at is None:
            amount_paid = Decimal(str(credit_supply.amount_paid or 0))

        refund_amount = amount_paid if supply.is_credit else Decimal(str(supply.total_price or 0))

        accounting_daily = DailyService.get_or_create_active_daily() or supply.daily
        exercise = accounting_daily.exercise if accounting_daily else supply.daily.exercise
        AccountingService.record_supply_cancellation(
            supply=supply,
            daily=accounting_daily,
            exercise=exercise,
            refund_payment_method=refund_payment_method,
            refund_amount=refund_amount,
        )

        product.stock -= supply.quantity
        product.save(update_fields=['stock'])

        if credit_supply and credit_supply.delete_at is None:
            credit_supply.delete_at = cancel_at
            credit_supply.save(update_fields=['delete_at'])
            PaymentSchedule.objects.filter(
                credit_supply=credit_supply,
                delete_at__isnull=True,
            ).update(delete_at=cancel_at)

        supply.delete_at = cancel_at
        supply.save(update_fields=['delete_at'])
        return refund_amount

    @staticmethod
    @transaction.atomic
    def partial_return_supply(supply, returned_quantity, reason='', refund_payment_method='CASH'):
        supply = Supply.objects.select_for_update().select_related(
            'product', 'supplier', 'daily', 'daily__exercise', 'credit_info', 'tax_rate'
        ).get(id=supply.id)

        if supply.delete_at is not None:
            raise ValueError(_("Cet approvisionnement est déjà annulé."))
        SupplyService._ensure_exercise_open(supply)

        returned_quantity = int(returned_quantity or 0)
        if returned_quantity <= 0:
            raise ValueError(_("Veuillez renseigner une quantité à retourner."))
        if returned_quantity >= supply.quantity:
            raise ValueError(_("Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale."))

        product = Product.objects.select_for_update().get(id=supply.product_id)
        if (product.stock or 0) < returned_quantity:
            raise ValueError(_(
                "Stock insuffisant pour effectuer ce retour fournisseur."
            ))

        previous_total = Decimal(str(supply.total_price or 0))
        previous_vat = Decimal(str(supply.vat_amount or 0))
        return_total = Decimal(str(supply.purchase_cost or 0)) * returned_quantity
        new_total = previous_total - return_total
        if new_total <= 0:
            raise ValueError(_("Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale."))

        refund_amount = Decimal('0')
        credit_supply = SupplyService._get_credit_supply(supply)
        if supply.is_credit:
            if credit_supply is None or credit_supply.delete_at is not None:
                raise ValueError(_("L'approvisionnement à crédit ne possède pas d'information de crédit active."))

            current_paid = Decimal(str(credit_supply.amount_paid or 0))
            refund_amount = max(current_paid - new_total, Decimal('0'))
            credit_supply.amount_paid = current_paid - refund_amount
            credit_supply.amount_remaining = max(new_total - credit_supply.amount_paid, Decimal('0'))
            credit_supply.is_fully_paid = credit_supply.amount_remaining <= 0
            supply.is_paid = credit_supply.is_fully_paid
            credit_supply.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])
            SupplyService._adjust_credit_schedules(credit_supply, return_total, reason=reason)
        else:
            refund_amount = return_total
            supply.is_paid = True

        supply_return = SupplyReturn.objects.create(
            supply=supply,
            quantity=returned_quantity,
            unit_cost=supply.purchase_cost,
            total=return_total,
            reason=reason or None,
            refund_amount=refund_amount,
            refund_payment_method=refund_payment_method if refund_amount > 0 else None,
        )

        product.stock -= returned_quantity
        product.save(update_fields=['stock'])

        if previous_total > 0:
            new_vat_amount = (previous_vat * new_total / previous_total).quantize(Decimal('0.01'))
        else:
            new_vat_amount = Decimal('0.00')

        supply.quantity -= returned_quantity
        supply.total_price = new_total
        supply.vat_amount = new_vat_amount
        supply.save(update_fields=['quantity', 'total_price', 'vat_amount', 'is_paid'])

        accounting_daily = DailyService.get_or_create_active_daily() or supply.daily
        exercise = accounting_daily.exercise if accounting_daily else supply.daily.exercise
        AccountingService.record_partial_supply_return(
            supply=supply,
            amount=return_total,
            daily=accounting_daily,
            exercise=exercise,
            refund_payment_method=refund_payment_method,
            refund_amount=refund_amount,
        )

        return supply_return, refund_amount