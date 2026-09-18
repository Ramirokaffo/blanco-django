"""
Rejoue les écritures comptables des ventes marquées ``accounting_pending``
(écriture échouée au moment de la vente : plan comptable incomplet, collision
de référence, etc.).

    python manage.py replay_accounting            # rejoue tout
    python manage.py replay_accounting --dry-run  # liste seulement
"""

from django.core.management.base import BaseCommand

from core.models import Sale, SystemSettings
from core.services.sale_service import SaleService


class Command(BaseCommand):
    help = "Rejoue les écritures comptables des ventes en attente."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="N'écrit rien, liste les ventes.")

    def handle(self, *args, **options):
        pending = Sale.objects.filter(
            accounting_pending=True, delete_at__isnull=True,
        ).select_related('daily', 'daily__exercise').order_by('id')
        count = pending.count()
        if count == 0:
            self.stdout.write("Aucune vente en attente d'écriture comptable.")
            return

        settings = SystemSettings.get_settings()
        enable_tva = getattr(settings, 'enable_tva_accounting', True)
        tva_mode = getattr(settings, 'tva_accounting_mode', 'IMMEDIATE')

        ok = 0
        for sale in pending:
            if options['dry_run']:
                self.stdout.write(f"Vente #{sale.id} — {sale.total} FCFA — journée #{sale.daily_id}")
                continue
            apply_tax = enable_tva and sale.has_vat and tva_mode == 'IMMEDIATE'
            if SaleService.record_sale_accounting(sale, sale.daily, apply_tax=apply_tax):
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"Vente #{sale.id} : écriture créée."))
            else:
                self.stdout.write(self.style.ERROR(f"Vente #{sale.id} : échec (voir les logs)."))

        if not options['dry_run']:
            self.stdout.write(f"{ok}/{count} vente(s) rejouée(s).")
