"""
Commande : python manage.py init_accounts

Initialise le plan comptable OHADA par défaut (comptes définis dans
core.services.accounting_service.DEFAULT_ACCOUNTS).

Idempotente : seuls les comptes manquants sont créés. Sans ces comptes, les
écritures comptables générées par les ventes, achats et dépenses échouent
silencieusement.

Note : cette initialisation est aussi exécutée automatiquement après chaque
`python manage.py migrate` (signal post_migrate, voir core/signals.py).
"""

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS

from core.models import Account
from core.services.accounting_service import AccountingService, DEFAULT_ACCOUNTS


class Command(BaseCommand):
    help = "Initialise le plan comptable OHADA par défaut (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            default=DEFAULT_DB_ALIAS,
            help="Base à peupler (multi-base : alias de la société visée).",
        )

    def handle(self, *args, **options):
        using = options['database']
        created = AccountingService.init_chart_of_accounts(using=using)
        total = Account.objects.db_manager(using).count()

        self.stdout.write(self.style.SUCCESS(
            f"✅ Plan comptable : {created} compte(s) créé(s), "
            f"{total} en base ({len(DEFAULT_ACCOUNTS)} attendus)."
        ))
