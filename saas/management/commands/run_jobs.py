"""
Commande : python manage.py run_jobs [--once] [--max-jobs N] [--kind KIND]

Processus de travail de la plateforme : provisionnement des nouveaux espaces,
envoi des e-mails, et plus tard sauvegardes et exports.

À lancer comme un service à part du serveur web (même image, autre commande),
avec redémarrage automatique : si ce processus s'arrête, les inscriptions
restent en attente sans que personne ne s'en aperçoive. Superviser l'âge du
plus ancien travail en file.
"""

from django.core.management.base import BaseCommand

from saas.jobs.runner import boucle
from saas.models import JobKind


class Command(BaseCommand):
    help = "Exécute les travaux différés de la plateforme."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="Traite au plus un travail puis rend la main.",
        )
        parser.add_argument(
            "--max-jobs", type=int, default=None,
            help="S'arrête après ce nombre de travaux.",
        )
        parser.add_argument(
            "--kind", action="append", choices=[k for k, _ in JobKind.choices],
            help="Ne traite que ces natures de travaux (répétable).",
        )
        parser.add_argument(
            "--interval", type=float, default=2.0,
            help="Attente entre deux sondages de la file, en secondes.",
        )

    def handle(self, *args, **options):
        natures = options.get("kind")
        traites = boucle(
            natures=natures,
            intervalle=options["interval"],
            max_jobs=options["max_jobs"],
            once=options["once"],
        )
        self.stdout.write(self.style.SUCCESS(
            "✅ %d travail/travaux traité(s)." % traites
        ))
