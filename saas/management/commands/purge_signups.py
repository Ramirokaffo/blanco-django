"""
Commande : python manage.py purge_signups [--dry-run]

Supprime les inscriptions jamais confirmées et libère leur sous-domaine.

L'entreprise est créée dès la soumission du formulaire, afin de réserver le
sous-domaine avec une seule contrainte d'unicité. Sans cette purge, un
sous-domaine abandonné resterait bloqué indéfiniment.
"""

from django.core.management.base import BaseCommand

from saas.constants import PURGE_INSCRIPTIONS_JOURS
from saas.models import Company, CompanyStatus
from saas.services.signup_service import purger_inscriptions_abandonnees


class Command(BaseCommand):
    help = "Supprime les inscriptions non confirmées et libère leur sous-domaine."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Affiche ce qui serait supprimé, sans rien supprimer.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            from django.utils import timezone

            limite = timezone.now() - timezone.timedelta(days=PURGE_INSCRIPTIONS_JOURS)
            concernees = Company.objects.filter(
                status=CompanyStatus.PENDING_VERIFICATION, create_at__lt=limite
            )
            for entreprise in concernees:
                self.stdout.write(f"  {entreprise.slug} — {entreprise.contact_email}")
            self.stdout.write(self.style.WARNING(
                "%d inscription(s) seraient supprimée(s)." % concernees.count()
            ))
            return

        supprimees = purger_inscriptions_abandonnees()
        self.stdout.write(self.style.SUCCESS(
            "✅ %d inscription(s) abandonnée(s) supprimée(s)." % supprimees
        ))
