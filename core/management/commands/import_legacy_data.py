"""
Commande : python manage.py import_legacy_data <dossier> [--apply-inventory]

Importe la base MySQL de l'ancien système Blanco (serveur Flask) dans une base
Django vierge, à partir des fichiers produits par mysqldump (un ou plusieurs
fichiers .sql, ex. old_data/blanco_product.sql). L'ordre des colonnes est lu
dans le CREATE TABLE de chaque dump, les INSERT n'ayant pas de liste de colonnes.

Les identifiants de l'ancien système sont conservés (mêmes id de produits,
ventes, utilisateurs...), ce qui garde les correspondances avec l'app mobile.

Choix de conversion :
- stock du produit = somme des `product_count_rest` des approvisionnements non
  supprimés (l'ancien système n'avait pas de champ stock) ; prix de vente et
  dernier prix d'achat = ceux du dernier approvisionnement ;
- `--apply-inventory` : le stock des produits comptés dans l'inventaire de
  l'exercice ouvert prend la quantité valide cumulée de ces comptages (comme le
  ferait une clôture d'inventaire, mais sans InventorySnapshot : la table
  impose un snapshot par produit et par exercice, ce qui bloquerait la
  prochaine clôture de ce même exercice) ;
- toutes les lignes d'inventaire importées sont marquées clôturées : le
  prochain inventaire repart de zéro ;
- une journée restée ouverte dans l'ancien système est fermée à sa dernière
  activité, sinon les ventes d'aujourd'hui s'y rattacheraient ;
- mots de passe : l'ancien système stockait un SHA-1 hexadécimal non salé,
  conservé au format `sha1$$<hash>` (UnsaltedSHA1PasswordHasher, voir
  PASSWORD_HASHERS) et re-haché en PBKDF2 à la première connexion ;
- les utilisateurs actifs reçoivent les modules utilisés par l'app mobile
  (ventes, produits, inventaire) : l'ancien système n'avait pas de droits ;
- aucune écriture comptable n'est générée pour l'historique ;
- les fichiers images ne sont pas dans le dump : les lignes pointent vers
  media/product/<fichier>, à copier à la main.

La base doit être vierge (après `migrate`) : la commande refuse de s'exécuter
si des données métier existent déjà. Tout se fait dans une seule transaction.
"""

import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from core.models import (
    AppModule, Category, Client, CustomUser, Daily, DailyExpense,
    DailyInventory, DailyRecipe, Exercise, ExpenseType, Gamme, GrammageType,
    Inventory, Product, ProductImage, Rayon, RecipeType, Sale, SaleProduct,
    Supply,
)
from core.services.migration_service import parse_sql_values

CREATE_RE = re.compile(r"CREATE TABLE `(\w+)` \((.*?)\n\) ENGINE", re.S)
COLUMN_RE = re.compile(r"^\s*`(\w+)`", re.M)
INSERT_RE = re.compile(r"^INSERT INTO `(\w+)` VALUES (.*);$", re.M)
SHA1_RE = re.compile(r"[0-9a-f]{40}")

# Tables de l'ancien système que la commande sait importer
HANDLED_TABLES = {
    'category', 'gamme', 'rayon', 'grammage_type', 'expense_type',
    'recipe_type', 'staff', 'client', 'exercise', 'daily', 'product',
    'product_image', 'supply', 'sale', 'sale_product', 'inventory',
    'daily_inventory', 'daily_expense', 'daily_recipe',
}
# Table de test sans valeur métier
IGNORED_TABLES = {'tdi_test'}

LEGACY_STAFF_MODULES = ('sales', 'products', 'inventory')

# Modèles dont des lignes existantes empêchent l'import
BUSINESS_MODELS = [
    Category, Gamme, Rayon, GrammageType, ExpenseType, RecipeType, Client,
    Exercise, Daily, Product, ProductImage, Supply, Sale, SaleProduct,
    Inventory, DailyInventory, DailyExpense, DailyRecipe,
]

CENT = Decimal('0.01')


def load_dump(folder):
    """Lit tous les .sql du dossier : {table: [ {colonne: valeur}, ... ]}."""
    columns = {}
    raw_rows = defaultdict(list)
    for path in sorted(Path(folder).glob('*.sql')):
        text = path.read_text(encoding='utf-8')
        for table, body in CREATE_RE.findall(text):
            columns[table] = COLUMN_RE.findall(body)
        for table, values in INSERT_RE.findall(text):
            raw_rows[table].extend(parse_sql_values(values))

    tables = {table: [] for table in columns}
    for table, rows in raw_rows.items():
        if table not in columns:
            raise CommandError(f"INSERT dans `{table}` sans CREATE TABLE correspondant.")
        names = columns[table]
        for row in rows:
            if len(row) != len(names):
                raise CommandError(
                    f"`{table}` : {len(row)} valeurs pour {len(names)} colonnes ({row[:3]}...)."
                )
            tables[table].append(dict(zip(names, row)))
    return tables


@contextmanager
def explicit_create_at(models):
    """Désactive auto_now_add pour conserver les dates d'origine."""
    fields = [model._meta.get_field('create_at') for model in models]
    saved = [field.auto_now_add for field in fields]
    for field in fields:
        field.auto_now_add = False
    try:
        yield
    finally:
        for field, value in zip(fields, saved):
            field.auto_now_add = value


class Command(BaseCommand):
    help = "Importe les dumps MySQL de l'ancien système Blanco dans une base vierge."

    def add_arguments(self, parser):
        parser.add_argument('folder', help="Dossier contenant les fichiers .sql de mysqldump.")
        parser.add_argument(
            '--apply-inventory',
            action='store_true',
            help="Applique au stock les comptages d'inventaire de l'exercice ouvert.",
        )

    def handle(self, *args, **options):
        folder = Path(options['folder'])
        if not folder.is_dir():
            raise CommandError(f"Dossier introuvable : {folder}")

        self.tz = ZoneInfo(settings.TIME_ZONE)
        self.now = timezone.now()
        self.warnings = []
        tables = load_dump(folder)

        unsupported = [
            f"{table} ({len(rows)})" for table, rows in tables.items()
            if rows and table not in HANDLED_TABLES | IGNORED_TABLES
        ]
        if unsupported:
            raise CommandError(
                "Tables non gérées contenant des données (elles seraient perdues) : "
                + ", ".join(unsupported)
            )
        missing = sorted(HANDLED_TABLES - tables.keys())
        if missing:
            raise CommandError("Dumps manquants : " + ", ".join(missing))

        self.check_empty_database(tables['staff'])

        with transaction.atomic(), explicit_create_at(BUSINESS_MODELS):
            stats = self.import_all(tables, options['apply_inventory'])
            self.reset_sequences()

        for message in self.warnings:
            self.stdout.write(self.style.WARNING(f"⚠️  {message}"))
        for label, value in stats.items():
            self.stdout.write(f"   {label} : {value}")
        self.stdout.write(self.style.SUCCESS("✅ Import des données de l'ancien système terminé."))

    # ── Garde-fous ───────────────────────────────────────────────────────

    def check_empty_database(self, legacy_staff):
        populated = [m._meta.db_table for m in BUSINESS_MODELS if m.objects.exists()]
        if populated:
            raise CommandError(
                "La base contient déjà des données (" + ", ".join(populated) + "). "
                "Partez d'une base vierge : supprimez db.sqlite3 puis lancez `migrate`."
            )
        ids = {row['id'] for row in legacy_staff}
        usernames = {row['username'] for row in legacy_staff}
        clash = CustomUser.objects.filter(id__in=ids) | CustomUser.objects.filter(username__in=usernames)
        if clash.exists():
            raise CommandError(
                "Des utilisateurs existants ont le même id ou identifiant que ceux de "
                "l'ancien système : importez avant de créer le superutilisateur."
            )

    # ── Conversions ──────────────────────────────────────────────────────

    def dt(self, value):
        """Date MySQL (heure locale de la boutique) → datetime aware."""
        if value is None:
            return None
        return timezone.make_aware(datetime.strptime(value, '%Y-%m-%d %H:%M:%S'), self.tz)

    @staticmethod
    def day(value):
        return date.fromisoformat(value) if value else None

    @staticmethod
    def money(value):
        return None if value is None else Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)

    @staticmethod
    def text(value):
        value = (str(value).strip() if value is not None else '')
        return value or None

    def ref(self, value, valid_ids, label, required=False):
        """Clé étrangère : None si la cible n'existe pas (erreur si obligatoire)."""
        if value is None or value in valid_ids:
            if value is None and required:
                raise CommandError(f"{label} : référence obligatoire absente.")
            return value
        if required:
            raise CommandError(f"{label} : référence {value} introuvable.")
        self.warnings.append(f"{label} : référence {value} introuvable, mise à vide.")
        return None

    # ── Import ───────────────────────────────────────────────────────────

    def import_lookup(self, model, rows):
        model.objects.bulk_create([
            model(
                id=row['id'], name=self.text(row['name']) or '',
                description=self.text(row['description']),
                create_at=self.dt(row['create_at']) or self.now,
                delete_at=self.dt(row['delete_at']),
            )
            for row in rows
        ])
        return {row['id'] for row in rows}

    def import_all(self, t, apply_inventory):
        category_ids = self.import_lookup(Category, t['category'])
        gamme_ids = self.import_lookup(Gamme, t['gamme'])
        rayon_ids = self.import_lookup(Rayon, t['rayon'])
        grammage_ids = self.import_lookup(GrammageType, t['grammage_type'])
        expense_type_ids = self.import_lookup(ExpenseType, t['expense_type'])
        recipe_type_ids = self.import_lookup(RecipeType, t['recipe_type'])

        # Utilisateurs
        users = []
        for row in t['staff']:
            password_hash = (row['password'] or '').lower()
            users.append(CustomUser(
                id=row['id'], username=row['username'],
                firstname=self.text(row['firstname']), lastname=self.text(row['lastname']),
                phone_number=self.text(row['phone_number']), email=self.text(row['email']) or '',
                role=row['role'], gender=self.text(row['gender']), profil=self.text(row['profil']),
                password=(
                    f"sha1$${password_hash}" if SHA1_RE.fullmatch(password_hash)
                    else make_password(None)
                ),
                date_joined=self.dt(row['create_at']) or self.now,
                delete_at=self.dt(row['delete_at']),
                is_active=bool(row['is_active']) and row['delete_at'] is None,
            ))
        CustomUser.objects.bulk_create(users)
        staff_ids = {u.id for u in users}

        AppModule.init_default_modules()
        modules = list(AppModule.objects.filter(code__in=LEGACY_STAFF_MODULES))
        for user in users:
            if user.is_active:
                user.allowed_modules.set(modules)

        Client.objects.bulk_create([
            Client(
                id=row['id'], firstname=self.text(row['firstname']),
                lastname=self.text(row['lastname']), phone_number=self.text(row['phone_number']),
                email=self.text(row['email']), gender=self.text(row['gender']),
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            )
            for row in t['client']
        ])
        client_ids = {row['id'] for row in t['client']}

        # Exercices et journées
        Exercise.objects.bulk_create([
            Exercise(
                id=row['id'], start_date=self.dt(row['start_date']),
                end_date=self.dt(row['end_date']), create_at=self.dt(row['start_date']),
            )
            for row in t['exercise']
        ])
        exercise_ids = {row['id'] for row in t['exercise']}
        open_exercise_ids = {row['id'] for row in t['exercise'] if row['end_date'] is None}

        daily_exercise = {}
        daily_last_activity = defaultdict(list)
        for table in ('sale', 'supply', 'daily_expense', 'daily_recipe', 'daily_inventory'):
            for row in t[table]:
                if row['daily_id'] is not None:
                    daily_last_activity[row['daily_id']].append(self.dt(row['create_at']))
        dailies = []
        closed_dailies = []
        for row in t['daily']:
            exercise_id = self.ref(row['exercise_id'], exercise_ids, f"Journée {row['id']}", required=True)
            daily_exercise[row['id']] = exercise_id
            start, end = self.dt(row['start_date']), self.dt(row['end_date'])
            if end is None:
                end = max([start] + [d for d in daily_last_activity[row['id']] if d])
                closed_dailies.append(row['id'])
            dailies.append(Daily(id=row['id'], start_date=start, end_date=end,
                                 exercise_id=exercise_id, create_at=start))
        Daily.objects.bulk_create(dailies)
        daily_ids = set(daily_exercise)

        # Produits : stock et prix déduits des approvisionnements
        stock = defaultdict(int)
        latest_price = {}
        latest_cost = {}
        for row in sorted(t['supply'], key=lambda r: (r['create_at'] or '', r['id'])):
            if row['delete_at'] is not None:
                continue
            stock[row['product_id']] += row['product_count_rest'] or 0
            if row['unit_price']:
                latest_price[row['product_id']] = self.money(row['unit_price'])
            if row['unit_coast']:
                latest_cost[row['product_id']] = self.money(row['unit_coast'])

        applied_inventory = {}
        if apply_inventory:
            for row in t['inventory']:
                if row['exercise_id'] in open_exercise_ids and row['delete_at'] is None:
                    applied_inventory[row['product_id']] = (
                        applied_inventory.get(row['product_id'], 0) + (row['valid_product_count'] or 0)
                    )
        stock.update(applied_inventory)

        products = []
        for row in t['product']:
            label = f"Produit {row['id']}"
            products.append(Product(
                id=row['id'], code=str(row['code']), name=str(row['name']),
                description=self.text(row['description']), brand=self.text(row['brand']),
                color=self.text(row['color']), stock=stock.get(row['id'], 0),
                stock_limit=row['stock_limit'], exp_alert_period=row['exp_alert_period'],
                grammage=row['grammage'],
                is_price_reducible=bool(row['is_price_reducible']) if row['is_price_reducible'] is not None else True,
                max_salable_price=self.money(row['max_salable_price']),
                actual_price=latest_price.get(row['id']),
                last_purchase_price=latest_cost.get(row['id']),
                category_id=self.ref(row['category_id'], category_ids, label),
                gamme_id=self.ref(row['gamme_id'], gamme_ids, label),
                grammage_type_id=self.ref(row['grammage_type_id'], grammage_ids, label),
                rayon_id=self.ref(row['rayon_id'], rayon_ids, label),
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            ))
        Product.objects.bulk_create(products)
        product_ids = {p.id for p in products}

        images = []
        has_primary = set()
        for row in sorted(t['product_image'], key=lambda r: r['id']):
            product_id = row['product_id']
            if product_id not in product_ids:
                self.warnings.append(f"Image {row['id']} ignorée : produit {product_id} introuvable.")
                continue
            is_primary = row['delete_at'] is None and product_id not in has_primary
            if is_primary:
                has_primary.add(product_id)
            images.append(ProductImage(
                id=row['id'], product_id=product_id,
                image=f"product/{Path(row['path']).name}", is_primary=is_primary,
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            ))
        ProductImage.objects.bulk_create(images)
        media_product = Path(settings.MEDIA_ROOT) / 'product'
        missing_files = sum(1 for img in images if not (media_product / Path(img.image.name).name).exists())

        # Approvisionnements
        supply_product = {}
        supplies = []
        for row in t['supply']:
            label = f"Approvisionnement {row['id']}"
            product_id = self.ref(row['product_id'], product_ids, label, required=True)
            supply_product[row['id']] = product_id
            purchase_cost = self.money(row['unit_coast']) or Decimal('0.00')
            supplies.append(Supply(
                id=row['id'], product_id=product_id,
                staff_id=self.ref(row['staff_id'], staff_ids, label),
                daily_id=self.ref(row['daily_id'], daily_ids, label, required=True),
                quantity=row['product_count'], purchase_cost=purchase_cost,
                selling_price=self.money(row['unit_price']),
                total_price=purchase_cost * row['product_count'],
                expiration_date=self.day(row['expiration_date']),
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            ))
        Supply.objects.bulk_create(supplies)

        # Ventes
        sales = []
        sale_created = {}
        for row in t['sale']:
            label = f"Vente {row['id']}"
            created = self.dt(row['create_at']) or self.now
            sale_created[row['id']] = created
            is_credit = bool(row['is_credit'])
            sales.append(Sale(
                id=row['id'], is_credit=is_credit,
                is_paid=bool(row['is_paid']) if row['is_paid'] is not None else not is_credit,
                total=self.money(row['total']),
                client_id=self.ref(row['client_id'], client_ids, label),
                staff_id=self.ref(row['staff_id'], staff_ids, label),
                daily_id=self.ref(row['daily_id'], daily_ids, label, required=True),
                create_at=created, delete_at=self.dt(row['delete_at']),
            ))
        Sale.objects.bulk_create(sales)

        sale_products = []
        for row in t['sale_product']:
            label = f"Ligne de vente {row['id']}"
            sale_id = self.ref(row['sale_id'], sale_created, label, required=True)
            supply_id = self.ref(row['supply_id'], supply_product, label, required=True)
            sale_products.append(SaleProduct(
                id=row['id'], sale_id=sale_id, product_id=supply_product[supply_id],
                quantity=row['product_count'], unit_price=self.money(row['unit_price']),
                create_at=sale_created[sale_id],
            ))
        SaleProduct.objects.bulk_create(sale_products)

        # Inventaires (tous clôturés)
        Inventory.objects.bulk_create([
            Inventory(
                id=row['id'],
                product_id=self.ref(row['product_id'], product_ids, f"Inventaire {row['id']}", required=True),
                staff_id=self.ref(row['staff_id'], staff_ids, f"Inventaire {row['id']}"),
                exercise_id=self.ref(row['exercise_id'], exercise_ids, f"Inventaire {row['id']}", required=True),
                valid_product_count=row['valid_product_count'] or 0,
                invalid_product_count=row['invalid_product_count'] or 0,
                is_close=True,
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            )
            for row in t['inventory']
        ])

        # Dépenses, recettes et clôtures de journée
        def daily_totals(rows, field):
            totals = defaultdict(Decimal)
            for row in rows:
                if row['delete_at'] is None and row['daily_id'] is not None and row[field] is not None:
                    totals[row['daily_id']] += self.money(row[field])
            return totals

        DailyExpense.objects.bulk_create([
            DailyExpense(
                id=row['id'], amount=self.money(row['amount']) or Decimal('0.00'),
                description=self.text(row['description']),
                expense_type_id=self.ref(row['raison_id'], expense_type_ids, f"Dépense {row['id']}"),
                staff_id=self.ref(row['staff_id'], staff_ids, f"Dépense {row['id']}"),
                daily_id=self.ref(row['daily_id'], daily_ids, f"Dépense {row['id']}", required=True),
                exercise_id=daily_exercise[row['daily_id']],
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            )
            for row in t['daily_expense']
        ])
        DailyRecipe.objects.bulk_create([
            DailyRecipe(
                id=row['id'], amount=self.money(row['amount']) or Decimal('0.00'),
                description=self.text(row['description']),
                recipe_type_id=self.ref(row['recipe_type_id'], recipe_type_ids, f"Recette {row['id']}"),
                staff_id=self.ref(row['staff_id'], staff_ids, f"Recette {row['id']}"),
                daily_id=self.ref(row['daily_id'], daily_ids, f"Recette {row['id']}", required=True),
                exercise_id=daily_exercise[row['daily_id']],
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            )
            for row in t['daily_recipe']
        ])

        sales_by_daily = daily_totals(t['sale'], 'total')
        expenses_by_daily = daily_totals(t['daily_expense'], 'amount')
        recipes_by_daily = daily_totals(t['daily_recipe'], 'amount')
        DailyInventory.objects.bulk_create([
            DailyInventory(
                id=row['id'],
                daily_id=self.ref(row['daily_id'], daily_ids, f"Clôture de journée {row['id']}", required=True),
                exercise_id=daily_exercise[row['daily_id']],
                staff_id=self.ref(row['staff_id'], staff_ids, f"Clôture de journée {row['id']}"),
                total_sales=sales_by_daily[row['daily_id']],
                total_expenses=expenses_by_daily[row['daily_id']],
                total_recipes=recipes_by_daily[row['daily_id']],
                cash_in_hand=self.money(row['cash_amount']) or Decimal('0.00'),
                cash_float=self.money(row['cash_float']) or Decimal('0.00'),
                create_at=self.dt(row['create_at']) or self.now, delete_at=self.dt(row['delete_at']),
            )
            for row in t['daily_inventory']
        ])

        if closed_dailies:
            self.warnings.append(
                "Journée(s) restée(s) ouverte(s) fermée(s) à leur dernière activité : "
                + ", ".join(map(str, closed_dailies))
            )
        if missing_files:
            self.warnings.append(
                f"{missing_files} image(s) sans fichier dans {media_product} : "
                "copiez-y les images de l'ancien serveur."
            )

        return {
            'Catégories / gammes / rayons / grammages': (
                f"{len(category_ids)} / {len(gamme_ids)} / {len(rayon_ids)} / {len(grammage_ids)}"
            ),
            'Utilisateurs': len(users),
            'Clients': len(client_ids),
            'Exercices / journées': f"{len(exercise_ids)} / {len(dailies)}",
            'Produits': len(products),
            'Produits en stock': sum(1 for p in products if p.stock > 0),
            'Stock appliqué depuis l\'inventaire': len(applied_inventory),
            'Images': len(images),
            'Approvisionnements': len(supplies),
            'Ventes / lignes': f"{len(sales)} / {len(sale_products)}",
            'Inventaires': len(t['inventory']),
            'Clôtures de journée': len(t['daily_inventory']),
            'Dépenses / recettes': f"{len(t['daily_expense'])} / {len(t['daily_recipe'])}",
        }

    def reset_sequences(self):
        """Recale les séquences d'id après insertion d'id explicites (PostgreSQL ; no-op ailleurs)."""
        models = BUSINESS_MODELS + [CustomUser]
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(), models):
                cursor.execute(sql)
