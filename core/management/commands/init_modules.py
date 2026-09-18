"""
Commande : python manage.py init_modules [--update]

Crée dans la base les modules applicatifs par défaut (onglets / fonctionnalités
définis dans core.models.settings_models.DEFAULT_MODULES).

Idempotente : seuls les modules manquants sont créés. Avec --update, le nom,
l'icône et l'ordre des modules déjà présents sont réalignés sur les valeurs
par défaut (les attributions par utilisateur et le champ `is_active` sont
conservés).

Note : cette initialisation est aussi exécutée automatiquement après chaque
`python manage.py migrate` (signal post_migrate, voir core/signals.py).
"""

from django.core.management.base import BaseCommand

from core.models.settings_models import AppModule, DEFAULT_MODULES


class Command(BaseCommand):
    help = "Crée les modules applicatifs par défaut (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help="Réaligne aussi le nom, l'icône et l'ordre des modules existants.",
        )

    def handle(self, *args, **options):
        created = AppModule.init_default_modules()
        updated = AppModule.sync_default_modules() if options['update'] else 0
        total = AppModule.objects.count()

        self.stdout.write(self.style.SUCCESS(
            f"✅ Modules applicatifs : {created} créé(s), {updated} mis à jour, "
            f"{total} en base ({len(DEFAULT_MODULES)} attendus)."
        ))

        if options['verbosity'] >= 2:
            for module in AppModule.objects.order_by('order', 'name'):
                state = 'actif' if module.is_active else 'inactif'
                self.stdout.write(f"   {module.order:>2}. {module.icon} {module.name} [{module.code}] ({state})")
