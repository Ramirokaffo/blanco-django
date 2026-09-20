"""
Tests du lot d'assainissement des migrations (préalable au multi-base) :

- propagation de l'alias de base (``using``) par le signal ``post_migrate``
  et par les fonctions de chargement des données de référence ;
- garde-fou ``check_migration_baseline`` (schéma incomplet, historique
  orphelin, réparation).
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.utils import ConnectionDoesNotExist
from django.test import TestCase

from core.models import Account
from core.models.settings_models import AppModule, DEFAULT_MODULES
from core.services.accounting_service import AccountingService, DEFAULT_ACCOUNTS
from core.signals import seed_default_data


class SeedDatabaseRoutingTests(TestCase):
    """
    Le chargement des données de référence doit viser une base explicite.

    Sans cela, ``migrate --database=<alias>`` peuplerait la base par défaut au
    lieu de celle qui vient d'être créée : en multi-base, la nouvelle société
    se retrouverait sans modules ni plan comptable.
    """

    ALIAS_INEXISTANT = 'base_qui_nexiste_pas'

    def test_init_default_modules_accepte_un_alias_explicite(self):
        AppModule.objects.all().delete()
        cree = AppModule.init_default_modules(using='default')
        self.assertEqual(cree, len(DEFAULT_MODULES))
        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))

    def test_init_default_modules_honore_reellement_lalias(self):
        # Un alias inconnu doit remonter : la preuve que le paramètre n'est
        # pas silencieusement ignoré (le bug que ce lot corrige).
        with self.assertRaises(ConnectionDoesNotExist):
            AppModule.init_default_modules(using=self.ALIAS_INEXISTANT)

    def test_sync_default_modules_honore_reellement_lalias(self):
        with self.assertRaises(ConnectionDoesNotExist):
            AppModule.sync_default_modules(using=self.ALIAS_INEXISTANT)

    def test_init_chart_of_accounts_accepte_un_alias_explicite(self):
        Account.objects.all().delete()
        cree = AccountingService.init_chart_of_accounts(using='default')
        self.assertEqual(cree, len(DEFAULT_ACCOUNTS))

    def test_init_chart_of_accounts_honore_reellement_lalias(self):
        with self.assertRaises(ConnectionDoesNotExist):
            AccountingService.init_chart_of_accounts(using=self.ALIAS_INEXISTANT)

    def test_le_parent_est_resolu_dans_la_meme_base(self):
        # 4431 a pour parent 443 : les deux doivent exister et être liés.
        Account.objects.all().delete()
        AccountingService.init_chart_of_accounts(using='default')
        compte = Account.objects.get(code='4431')
        self.assertIsNotNone(compte.parent)
        self.assertEqual(compte.parent.code, '443')

    def test_le_signal_post_migrate_transmet_lalias(self):
        # post_migrate envoie `using` : le gestionnaire doit le propager.
        with self.assertRaises(ConnectionDoesNotExist):
            seed_default_data(sender=None, using=self.ALIAS_INEXISTANT, verbosity=0)

    def test_le_signal_reste_idempotent_sans_alias(self):
        seed_default_data(sender=None, verbosity=0)
        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))
        self.assertEqual(Account.objects.count(), len(DEFAULT_ACCOUNTS))

    def test_les_commandes_acceptent_loption_database(self):
        AppModule.objects.all().delete()
        Account.objects.all().delete()

        call_command('init_modules', '--database', 'default', stdout=StringIO())
        call_command('init_accounts', '--database', 'default', stdout=StringIO())

        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))
        self.assertEqual(Account.objects.count(), len(DEFAULT_ACCOUNTS))


class CheckMigrationBaselineTests(TestCase):
    """
    Garde-fou exécuté avant `migrate` sur une installation déjà déployée.

    Rappel du risque couvert : `django_migrations` ne stocke aucun condensat du
    contenu des migrations. Une installation dont le schéma a raté des
    changements de modèle accepterait donc nos migrations « déjà appliquées »
    tout en restant incomplète.
    """

    MIGRATION_ORPHELINE = '0002_migration_generee_localement'

    def _executer(self, *args):
        sortie = StringIO()
        call_command('check_migration_baseline', *args, stdout=sortie, stderr=sortie)
        return sortie.getvalue()

    def _inserer_migration_orpheline(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO django_migrations (app, name, applied) "
                "VALUES (%s, %s, CURRENT_TIMESTAMP)",
                ['core', self.MIGRATION_ORPHELINE],
            )

    def _compter_migration_orpheline(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = %s AND name = %s",
                ['core', self.MIGRATION_ORPHELINE],
            )
            return cursor.fetchone()[0]

    def test_base_a_jour_est_declaree_coherente(self):
        self.assertIn('cohérents', self._executer())

    def test_historique_orphelin_avertit_sans_bloquer(self):
        self._inserer_migration_orpheline()
        sortie = self._executer()
        self.assertIn('Schéma conforme', sortie)
        self.assertIn(self.MIGRATION_ORPHELINE, sortie)
        # Non bloquant : l'entrée est conservée tant qu'on ne répare pas.
        self.assertEqual(self._compter_migration_orpheline(), 1)

    def test_reparation_supprime_lentree_orpheline(self):
        self._inserer_migration_orpheline()
        sortie = self._executer('--repair-history')
        self.assertIn('Historique nettoyé', sortie)
        self.assertEqual(self._compter_migration_orpheline(), 0)

    def test_colonne_manquante_bloque_la_mise_a_jour(self):
        # On simule une installation qui n'a jamais reçu `accounting_pending`
        # (exactement le scénario de l'ancien `makemigrations` au démarrage).
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE sale DROP COLUMN accounting_pending')

        with self.assertRaises(CommandError) as ctx:
            self._executer()

        message = str(ctx.exception)
        self.assertIn('ne correspond pas aux modèles', message)
        self.assertIn('sale.accounting_pending', message)
        self.assertIn("N'appliquez RIEN", message)

    def test_reparation_refusee_si_le_schema_est_incomplet(self):
        # Le nettoyage d'historique ne doit jamais masquer un schéma cassé.
        self._inserer_migration_orpheline()
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE sale DROP COLUMN accounting_pending')

        with self.assertRaises(CommandError):
            self._executer('--repair-history')
        self.assertEqual(self._compter_migration_orpheline(), 1)
