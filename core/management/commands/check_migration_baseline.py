"""
Commande : python manage.py check_migration_baseline [--database <alias>]
                                                     [--strict] [--repair-history]

Garde-fou de mise à jour, appelé par docker-entrypoint.sh AVANT `migrate`.

Contexte historique
-------------------
Jusqu'au passage au multi-base, les migrations n'étaient pas versionnées :
`.gitignore` les excluait et l'entrypoint lançait `makemigrations` à chaque
démarrage. Chaque installation a donc enregistré dans `django_migrations` un
`core.0001_initial` **généré localement**, dont le contenu reflète les modèles
du jour de son installation — parfois suivi d'un `0002_...` tout aussi local.

Comme `django_migrations` ne stocke que `(app, name, applied)` — jamais un
condensat du contenu — Django considère notre `0001_initial` versionné comme
déjà appliqué et ne touche pas au schéma. La mise à jour est donc transparente,
MAIS uniquement si le schéma réel contient bien tout ce que décrivent les
modèles actuels. Si l'installation a raté des changements de modèle (cas
classique : `makemigrations` régénérait un 0001 que `migrate` croyait déjà
appliqué), il lui manque des colonnes et l'application plantera à l'exécution.

Ce que cette commande vérifie
-----------------------------
1. **Le schéma** : chaque table des modèles `core` existe et porte toutes les
   colonnes attendues. C'est le contrôle qui compte — il détecte précisément
   les colonnes jamais créées.
2. **L'historique** : une migration `core` enregistrée en base mais absente du
   dossier `core/migrations/` signale une migration générée localement.
   Bénin si le schéma est conforme (`--repair-history` nettoie l'entrée
   orpheline), bloquant sinon.
3. **Une base peuplée sans historique** (import legacy) : `migrate` tenterait
   un CREATE TABLE sur des tables existantes ; la manœuvre de rattrapage est
   indiquée.
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.loader import MigrationLoader


class Command(BaseCommand):
    help = (
        "Vérifie que le schéma et l'historique des migrations d'une base sont "
        "compatibles avec les migrations livrées (garde-fou de mise à jour)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            default=DEFAULT_DB_ALIAS,
            help="Base à contrôler (multi-base : alias de la société visée).",
        )
        parser.add_argument(
            '--strict',
            action='store_true',
            help="Échoue aussi lorsque des migrations livrées restent à appliquer.",
        )
        parser.add_argument(
            '--repair-history',
            action='store_true',
            help=(
                "Supprime les entrées d'historique orphelines (migrations "
                "enregistrées dont le fichier n'existe plus). Refusé si le "
                "schéma n'est pas conforme."
            ),
        )

    # ── Contrôle du schéma ────────────────────────────────────────────

    def _controler_schema(self, connection):
        """
        Compare les colonnes attendues par les modèles `core` à celles réellement
        présentes. Retourne (tables_manquantes, colonnes_manquantes).
        """
        tables_existantes = set(connection.introspection.table_names())
        tables_manquantes = []
        colonnes_manquantes = []

        with connection.cursor() as cursor:
            for model in apps.get_app_config('core').get_models():
                if not model._meta.managed:
                    continue
                table = model._meta.db_table
                if table not in tables_existantes:
                    tables_manquantes.append(table)
                    continue

                reelles = {
                    col.name.lower()
                    for col in connection.introspection.get_table_description(cursor, table)
                }
                for field in model._meta.local_fields:
                    colonne = field.column
                    if colonne and colonne.lower() not in reelles:
                        colonnes_manquantes.append(f"{table}.{colonne}")

                # Tables de liaison des ManyToMany (ex. staff_allowed_modules)
                for field in model._meta.local_many_to_many:
                    through = field.remote_field.through
                    if through._meta.auto_created and through._meta.db_table not in tables_existantes:
                        tables_manquantes.append(through._meta.db_table)

        return tables_manquantes, colonnes_manquantes

    # ── Point d'entrée ────────────────────────────────────────────────

    def handle(self, *args, **options):
        using = options['database']
        connection = connections[using]
        tables = set(connection.introspection.table_names())

        # Base vierge : `migrate` fera tout le travail, rien à contrôler.
        if 'django_migrations' not in tables:
            if tables:
                raise CommandError(
                    "La base « %s » contient %d table(s) mais aucun historique de "
                    "migrations : un `migrate` tenterait de recréer des tables "
                    "existantes.\n"
                    "Rattrapage : python manage.py migrate core 0001 --fake --database=%s"
                    % (using, len(tables), using)
                )
            self.stdout.write(self.style.SUCCESS(
                "✅ Base « %s » vierge : rien à contrôler." % using
            ))
            return

        tables_manquantes, colonnes_manquantes = self._controler_schema(connection)

        loader = MigrationLoader(connection, ignore_no_migrations=True)
        sur_disque = {n for app, n in loader.disk_migrations if app == 'core'}
        en_base = {n for app, n in loader.applied_migrations if app == 'core'}
        orphelines = sorted(en_base - sur_disque)
        non_appliquees = sorted(sur_disque - en_base)

        schema_conforme = not tables_manquantes and not colonnes_manquantes

        # 1. Schéma incomplet : c'est le cas grave.
        if not schema_conforme:
            details = []
            if tables_manquantes:
                details.append("tables absentes : " + ", ".join(sorted(tables_manquantes)))
            if colonnes_manquantes:
                details.append("colonnes absentes : " + ", ".join(sorted(colonnes_manquantes)))
            raise CommandError(
                "Le schéma de la base « %s » ne correspond pas aux modèles.\n  %s\n\n"
                "Cette installation n'a jamais reçu certains changements de modèle "
                "(ancien fonctionnement : `makemigrations` au démarrage régénérait "
                "un 0001_initial que `migrate` croyait déjà appliqué).\n"
                "N'appliquez RIEN : une migration de rattrapage doit être écrite "
                "pour cette installation avant la mise à jour."
                % (using, "\n  ".join(details))
            )

        # 2. Schéma conforme mais historique pollué par des migrations locales.
        if orphelines:
            if options['repair_history']:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM django_migrations WHERE app = %%s AND name IN (%s)"
                        % ", ".join(["%s"] * len(orphelines)),
                        ['core', *orphelines],
                    )
                self.stdout.write(self.style.SUCCESS(
                    "✅ Historique nettoyé sur « %s » : %d entrée(s) orpheline(s) "
                    "supprimée(s) (%s). Le schéma était conforme."
                    % (using, len(orphelines), ', '.join(orphelines))
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    "⚠️  Schéma conforme, mais %d migration(s) enregistrée(s) sans "
                    "fichier correspondant sur « %s » : %s.\n"
                    "   Ce sont des migrations générées localement par l'ancien "
                    "fonctionnement. Le schéma étant correct, elles peuvent être "
                    "retirées de l'historique :\n"
                    "   python manage.py check_migration_baseline --repair-history --database=%s"
                    % (len(orphelines), using, ', '.join(orphelines), using)
                ))
            return

        # 3. Cas nominal.
        if non_appliquees:
            message = (
                "%d migration(s) livrée(s) restent à appliquer sur « %s » : %s."
                % (len(non_appliquees), using, ', '.join(non_appliquees))
            )
            if options['strict']:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING("⚠️  " + message))
            return

        self.stdout.write(self.style.SUCCESS(
            "✅ Schéma et historique cohérents sur « %s » (%d migration(s) appliquée(s))."
            % (using, len(en_base))
        ))
