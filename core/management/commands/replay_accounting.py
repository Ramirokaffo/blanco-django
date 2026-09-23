"""
Rejoue les écritures comptables marquées ``accounting_pending`` (écriture
échouée au moment de l'enregistrement : plan comptable incomplet, collision
de référence, etc.) pour les ventes, dépenses, recettes et paiements
fournisseurs.

    python manage.py replay_accounting            # rejoue tout
    python manage.py replay_accounting --dry-run  # liste seulement
"""

from django.core.management.base import BaseCommand

from core.models import Sale, SystemSettings
from core.models.accounting_models import DailyExpense, DailyRecipe, SupplierPayment
from core.services.accounting_service import AccountingService
from core.services.excercise_service import ExerciseService
from core.services.sale_service import SaleService


class Command(BaseCommand):
    help = "Rejoue les écritures comptables en attente (ventes, dépenses, recettes, paiements fournisseurs)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="N'écrit rien, liste les éléments en attente.")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        ok = 0
        count = 0

        c, o = self._replay_sales(dry_run)
        count += c
        ok += o

        c, o = self._replay_expenses(dry_run)
        count += c
        ok += o

        c, o = self._replay_recipes(dry_run)
        count += c
        ok += o

        c, o = self._replay_supplier_payments(dry_run)
        count += c
        ok += o

        if count == 0:
            self.stdout.write("Aucune écriture comptable en attente.")
        elif not dry_run:
            self.stdout.write(f"{ok}/{count} écriture(s) rejouée(s) au total.")

    def _replay_sales(self, dry_run):
        pending = Sale.objects.filter(
            accounting_pending=True, delete_at__isnull=True,
        ).select_related('daily', 'daily__exercise').order_by('id')
        count = pending.count()
        if count == 0:
            return 0, 0

        settings = SystemSettings.get_settings()
        enable_tva = getattr(settings, 'enable_tva_accounting', True)
        tva_mode = getattr(settings, 'tva_accounting_mode', 'IMMEDIATE')

        ok = 0
        for sale in pending:
            if dry_run:
                self.stdout.write(f"Vente #{sale.id} — {sale.total} FCFA — journée #{sale.daily_id}")
                continue
            apply_tax = enable_tva and sale.has_vat and tva_mode == 'IMMEDIATE'
            if SaleService.record_sale_accounting(sale, sale.daily, apply_tax=apply_tax):
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"Vente #{sale.id} : écriture créée."))
            else:
                self.stdout.write(self.style.ERROR(f"Vente #{sale.id} : échec (voir les logs)."))
        return count, ok

    def _replay_expenses(self, dry_run):
        pending = DailyExpense.objects.filter(
            accounting_pending=True, delete_at__isnull=True,
        ).select_related('daily', 'exercise').order_by('id')
        count = pending.count()
        if count == 0:
            return 0, 0

        ok = 0
        for expense in pending:
            if dry_run:
                self.stdout.write(f"Dépense #{expense.id} — {expense.amount} FCFA — journée #{expense.daily_id}")
                continue
            if AccountingService.safe_record_expense(
                expense, daily=expense.daily, exercise=expense.exercise,
                payment_method='CASH',
            ):
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"Dépense #{expense.id} : écriture créée."))
            else:
                self.stdout.write(self.style.ERROR(f"Dépense #{expense.id} : échec (voir les logs)."))
        return count, ok

    def _replay_recipes(self, dry_run):
        pending = DailyRecipe.objects.filter(
            accounting_pending=True, delete_at__isnull=True,
        ).select_related('daily', 'exercise').order_by('id')
        count = pending.count()
        if count == 0:
            return 0, 0

        ok = 0
        for recipe in pending:
            if dry_run:
                self.stdout.write(f"Recette #{recipe.id} — {recipe.amount} FCFA — journée #{recipe.daily_id}")
                continue
            if AccountingService.safe_record_recipe(
                recipe, daily=recipe.daily, exercise=recipe.exercise,
                payment_method='CASH',
            ):
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"Recette #{recipe.id} : écriture créée."))
            else:
                self.stdout.write(self.style.ERROR(f"Recette #{recipe.id} : échec (voir les logs)."))
        return count, ok

    def _replay_supplier_payments(self, dry_run):
        pending = SupplierPayment.objects.filter(
            accounting_pending=True, delete_at__isnull=True,
        ).select_related('daily', 'daily__exercise').order_by('id')
        count = pending.count()
        if count == 0:
            return 0, 0

        ok = 0
        for payment in pending:
            if dry_run:
                self.stdout.write(f"Paiement fournisseur #{payment.id} — {payment.amount} FCFA")
                continue
            exercise = payment.daily.exercise if payment.daily else ExerciseService.get_or_create_current_exercise()
            if AccountingService.safe_record_supplier_payment(
                payment, daily=payment.daily, exercise=exercise,
            ):
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"Paiement fournisseur #{payment.id} : écriture créée."))
            else:
                self.stdout.write(self.style.ERROR(f"Paiement fournisseur #{payment.id} : échec (voir les logs)."))
        return count, ok
