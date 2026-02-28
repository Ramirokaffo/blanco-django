"""
Service comptable : initialisation du plan comptable OHADA et génération
automatique des écritures comptables (partie double).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models.accounting_models import (
    Account, JournalEntry, JournalEntryLine,
    PAYMENT_METHOD_ACCOUNT_MAP, TaxRate,
)


# ──────────────────────────────────────────────────────────────────────────────
# Plan comptable OHADA simplifié (comptes les plus courants pour le commerce)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_ACCOUNTS = [
    # Classe 1 – Capitaux propres
    ('12', 'Résultat de l\'exercice', 'PASSIF', None),
    ('13', 'Report à nouveau', 'PASSIF', None),
    ('131', 'Report à nouveau (solde créditeur)', 'PASSIF', '13'),
    ('139', 'Report à nouveau (solde débiteur)', 'ACTIF', '13'),
    # Classe 3 – Stocks
    ('31', 'Stocks de marchandises', 'ACTIF', None),
    # Classe 4 – Tiers
    ('401', 'Fournisseurs', 'PASSIF', None),
    ('411', 'Clients', 'ACTIF', None),
    ('443', 'État, TVA facturée', 'PASSIF', None),
    ('4431', 'TVA facturée sur ventes', 'PASSIF', '443'),
    ('445', 'État, TVA récupérable', 'ACTIF', None),
    ('4451', 'TVA récupérable sur achats', 'ACTIF', '445'),
    ('4441', 'État, TVA due', 'PASSIF', None),
    # Classe 5 – Trésorerie
    ('52', 'Banques', 'ACTIF', None),
    ('521', 'Banque locale', 'ACTIF', '52'),
    ('57', 'Caisse', 'ACTIF', None),
    ('571', 'Caisse principale', 'ACTIF', '57'),
    ('58', 'Virements internes', 'ACTIF', None),
    ('585', 'Mobile Money', 'ACTIF', '58'),
    # Classe 6 – Charges
    ('601', "Achats de marchandises", 'CHARGE', None),
    ('6031', "Variations de stocks de marchandises", 'CHARGE', None),
    ('61', "Transports", 'CHARGE', None),
    ('62', "Services extérieurs", 'CHARGE', None),
    ('63', "Autres services extérieurs", 'CHARGE', None),
    ('64', "Charges de personnel", 'CHARGE', None),
    ('65', "Autres charges", 'CHARGE', None),
    # Classe 7 – Produits
    ('701', 'Ventes de marchandises', 'PRODUIT', None),
    ('71', "Production stockée", 'PRODUIT', None),
    ('75', 'Autres produits', 'PRODUIT', None),
    ('758', 'Produits divers', 'PRODUIT', None),
]


class AccountingService:
    """Service principal pour la comptabilité."""

    # ── Initialisation du plan comptable ──────────────────────────────

    @staticmethod
    def init_chart_of_accounts():
        """
        Initialise le plan comptable OHADA avec les comptes par défaut.
        Ne crée que les comptes manquants (idempotent).
        Retourne le nombre de comptes créés.
        """
        created_count = 0
        for code, name, account_type, parent_code in DEFAULT_ACCOUNTS:
            parent = None
            if parent_code:
                parent = Account.objects.filter(code=parent_code).first()
            _, created = Account.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'account_type': account_type,
                    'parent': parent,
                },
            )
            if created:
                created_count += 1
        return created_count

    # ── Génération de référence unique ────────────────────────────────

    @staticmethod
    def _generate_reference(journal_code: str) -> str:
        """Génère une référence unique : VE-20260225-001"""
        today = date.today().strftime('%Y%m%d')
        prefix = f"{journal_code}-{today}"
        last = (
            JournalEntry.objects
            .filter(reference__startswith=prefix)
            .order_by('-reference')
            .first()
        )
        if last:
            seq = int(last.reference.split('-')[-1]) + 1
        else:
            seq = 1
        return f"{prefix}-{seq:03d}"

    # ── Helpers pour récupérer un compte ──────────────────────────────

    @staticmethod
    def get_account(code: str) -> Account:
        """Récupère un compte par son code. Lève DoesNotExist si absent."""
        return Account.objects.get(code=code)

    # ── Helper TVA ──────────────────────────────────────────────────

    @staticmethod
    def get_default_tax_rate():
        """Récupère le taux de TVA par défaut (ou None si pas de TVA active)."""
        return TaxRate.objects.filter(
            is_default=True, is_active=True, delete_at__isnull=True
        ).first()

    @staticmethod
    def compute_tax(amount_ttc, tax_rate):
        """
        Calcule le HT et la TVA à partir d'un montant TTC.
        Formule : HT = TTC / (1 + taux), TVA = TTC - HT
        """
        if not tax_rate or tax_rate.rate <= 0:
            return amount_ttc, Decimal('0')
        rate = tax_rate.rate / Decimal('100')
        ht = (amount_ttc / (1 + rate)).quantize(Decimal('1'))
        tva = amount_ttc - ht
        return ht, tva

    # ── Écriture pour une VENTE ───────────────────────────────────────

    @classmethod
    def record_sale(cls, sale, daily, exercise, payment_method='CASH',
                    apply_tax=False):
        """
        Enregistre l'écriture comptable d'une vente.
        Sans TVA :
          Débit  571/521/585 (ou 411)  | TTC
          Crédit 701                   | TTC
        Avec TVA :
          Débit  571/521/585 (ou 411)  | TTC
          Crédit 701                   | HT
          Crédit 4431 TVA collectée    | TVA
        """
        amount = Decimal(str(sale.total or 0))
        if amount <= 0:
            return None

        is_credit = getattr(sale, 'is_credit', False)

        # Calcul TVA si activée
        tax_rate = cls.get_default_tax_rate() if apply_tax else None
        ht, tva = cls.compute_tax(amount, tax_rate)

        with transaction.atomic():
            ref = cls._generate_reference('VE')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Vente #{sale.id}" + (" (crédit)" if is_credit else "")
                            + (f" TVA {tax_rate.rate}%" if tax_rate else ""),
                journal='VE',
                exercise=exercise,
                daily=daily,
                sale=sale,
            )

            if is_credit:
                debit_account = cls.get_account('411')
                debit_desc = f"Créance client – vente #{sale.id}"
            else:
                account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(payment_method, '571')
                debit_account = cls.get_account(account_code)
                debit_desc = f"Encaissement vente #{sale.id}"

            lines = [
                JournalEntryLine(
                    entry=entry,
                    account=debit_account,
                    debit=amount, credit=0,
                    description=debit_desc,
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('701'),
                    debit=0, credit=ht,
                    description=f"Vente de marchandises #{sale.id} (HT)",
                ),
            ]

            if tva > 0:
                lines.append(JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('4431'),
                    debit=0, credit=tva,
                    description=f"TVA collectée – vente #{sale.id}",
                ))

            JournalEntryLine.objects.bulk_create(lines)
        return entry

    # ── Écritures TVA différées pour un Daily ─────────────────────────────

    @classmethod
    def record_deferred_tva_for_daily(cls, daily):
        """
        Enregistre les écritures de TVA différée pour toutes les ventes du Daily
        qui n'ont pas encore eu leurs écritures TVA créées.
        
        Utilisé en mode DEFERRED lors de la clôture du Daily.
        
        :param daily: Objet Daily pour lequel créer les écritures TVA
        :return: Nombre d'écritures créées
        """
        from core.models import Sale
        
        # Récupérer les ventes avec TVA qui n'ont pas encore d'écritures TVA
        sales_with_tva = Sale.objects.filter(
            daily=daily,
            has_vat=True,
            tva_accounting_created=False,
            delete_at__isnull=True,
        )
        
        if not sales_with_tva.exists():
            return 0
        
        tax_rate = cls.get_default_tax_rate()
        if not tax_rate:
            return 0
        
        entries_created = 0
        
        with transaction.atomic():
            for sale in sales_with_tva:
                try:
                    amount = Decimal(str(sale.total or 0))
                    if amount <= 0:
                        continue
                        
                    ht, tva = cls.compute_tax(amount, tax_rate)
                    
                    if tva <= 0:
                        continue
                    
                    # Créer une écriture de TVA collectée
                    ref = cls._generate_reference('VE')
                    entry = JournalEntry.objects.create(
                        reference=ref,
                        date=timezone.now().date(),
                        description=f"TVA collectée - Vente #{sale.id} (clôture daily)",
                        journal='VE',
                        exercise=daily.exercise,
                        daily=daily,
                        sale=sale,
                    )
                    
                    # Créditer le compte de TVA collectée
                    JournalEntryLine.objects.create(
                        entry=entry,
                        account=cls.get_account('4431'),
                        debit=0,
                        credit=tva,
                        description=f"TVA collectée – vente #{sale.id}",
                    )
                    
                    # Marquer la vente comme ayant ses écritures TVA créées
                    sale.tva_accounting_created = True
                    sale.save(update_fields=['tva_accounting_created'])
                    
                    entries_created += 1
                    
                except Exception as e:
                    # Log l'erreur mais continuer avec les autres ventes
                    print(f"Erreur lors de la création des écritures TVA pour la vente #{sale.id}: {e}")
                    continue
        
        return entries_created

    # ── Écriture pour un ACHAT / Approvisionnement ────────────────────

    @classmethod
    def record_supply(cls, supply, daily, exercise,
                      payment_method='CASH', is_credit=False,
                      tax_rate=None):
        """
        Enregistre l'écriture comptable d'un approvisionnement.
        Sans TVA :
          Débit  601             | TTC
          Crédit 571/521/585/401 | TTC
        Avec TVA :
          Débit  601              | HT
          Débit  4451 TVA déduct. | TVA
          Crédit 571/521/585/401  | TTC
        
        :param tax_rate: objet TaxRate optionnel. Si fourni, la TVA sera calculée.
        """
        amount = Decimal(str(supply.total_price or 0))
        if amount <= 0:
            return None

        ht, tva = cls.compute_tax(amount, tax_rate)

        with transaction.atomic():
            ref = cls._generate_reference('AC')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Approvisionnement #{supply.id} – {supply.product.name}"
                            + (" (crédit)" if is_credit else "")
                            + (f" TVA {tax_rate.rate}%" if tax_rate else ""),
                journal='AC',
                exercise=exercise,
                daily=daily,
                supply=supply,
            )

            if is_credit:
                credit_account = cls.get_account('401')
                credit_desc = f"Dette fournisseur – appro. #{supply.id}"
            else:
                account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(payment_method, '571')
                credit_account = cls.get_account(account_code)
                credit_desc = f"Paiement fournisseur – appro. #{supply.id}"

            lines = [
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('601'),
                    debit=ht, credit=0,
                    description=f"Achat {supply.product.name} (HT)",
                ),
                JournalEntryLine(
                    entry=entry,
                    account=credit_account,
                    debit=0, credit=amount,
                    description=credit_desc,
                ),
            ]

            if tva > 0:
                lines.append(JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('4451'),
                    debit=tva, credit=0,
                    description=f"TVA déductible – appro. #{supply.id}",
                ))

            JournalEntryLine.objects.bulk_create(lines)
        return entry

    # ── Écriture pour une DÉPENSE ─────────────────────────────────────

    @classmethod
    def record_expense(cls, expense, daily, exercise, payment_method='CASH'):
        """
        Enregistre l'écriture comptable d'une dépense.
        Débit  65  Autres charges      | montant
        Crédit 571/521/585 Trésorerie  | montant
        
        Si expense.account est défini, utilise ce compte au lieu de 65.
        """
        amount = Decimal(str(expense.amount or 0))
        if amount <= 0:
            return None

        account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(payment_method, '571')
        
        # Utiliser le compte sélectionné dans la dépense ou défaut 65
        if expense.account:
            expense_account = expense.account
        else:
            expense_account = cls.get_account('65')

        with transaction.atomic():
            ref = cls._generate_reference('CA')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Dépense – {expense.expense_type.name if expense.expense_type else 'Divers'}",
                journal='CA',
                exercise=exercise,
                daily=daily,
                expense=expense,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=expense_account,
                    debit=amount, credit=0,
                    description=expense.description or f"Dépense #{expense.id}",
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=0, credit=amount,
                    description=f"Sortie de caisse – dépense #{expense.id}",
                ),
            ])
        return entry

    # ── Écriture pour une RECETTE ───────────────────────────────────────

    @classmethod
    def record_recipe(cls, recipe, daily, exercise, payment_method='CASH'):
        """
        Enregistre l'écriture comptable d'une recette.
        Débit  571/521/585 Trésorerie  | montant
        Crédit 75  Autres produits     | montant
        
        Si recipe.account est défini, utilise ce compte au lieu de 75.
        """
        amount = Decimal(str(recipe.amount or 0))
        if amount <= 0:
            return None

        account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(payment_method, '571')
        
        # Utiliser le compte sélectionné dans la recette ou défaut 75
        if recipe.account:
            recipe_account = recipe.account
        else:
            recipe_account = cls.get_account('75')

        with transaction.atomic():
            ref = cls._generate_reference('CA')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Recette – {recipe.recipe_type.name if recipe.recipe_type else 'Divers'}",
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=amount, credit=0,
                    description=f"Entrée de caisse – recette #{recipe.id}",
                ),
                JournalEntryLine(
                    entry=entry,
                    account=recipe_account,
                    debit=0, credit=amount,
                    description=recipe.description or f"Recette #{recipe.id}",
                ),
            ])
        return entry

    # ── Écriture pour un PAIEMENT CRÉDIT CLIENT ────────────────────────

    @classmethod
    def record_credit_payment(cls, payment, daily, exercise):
        """
        Enregistre l'écriture comptable d'un paiement reçu sur vente à crédit.
        Débit  571/521/585 (Trésorerie) | montant
        Crédit 411         (Clients)    | montant
        """
        amount = Decimal(str(payment.amount or 0))
        if amount <= 0:
            return None

        account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(payment.payment_method, '571')

        with transaction.atomic():
            ref = cls._generate_reference('CA')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Paiement crédit – Vente #{payment.credit_sale.sale_id}",
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=amount, credit=0,
                    description=f"Encaissement crédit – Vente #{payment.credit_sale.sale_id}",
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('411'),
                    debit=0, credit=amount,
                    description=f"Règlement client – Vente #{payment.credit_sale.sale_id}",
                ),
            ])
        return entry

    # ── Écriture pour un PAIEMENT FOURNISSEUR ──────────────────────────

    @classmethod
    def record_supplier_payment(cls, supplier_payment, daily, exercise):
        """
        Enregistre l'écriture comptable d'un paiement fournisseur.
        Débit  401 (Fournisseurs)       | montant
        Crédit 571/521/585 (Trésorerie) | montant
        """
        amount = Decimal(str(supplier_payment.amount or 0))
        if amount <= 0:
            return None

        account_code = PAYMENT_METHOD_ACCOUNT_MAP.get(
            supplier_payment.payment_method, '571'
        )

        with transaction.atomic():
            ref = cls._generate_reference('CA')
            entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Paiement fournisseur – {supplier_payment.supplier.name}",
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('401'),
                    debit=amount, credit=0,
                    description=f"Règlement fournisseur – {supplier_payment.supplier.name}",
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=0, 
                    credit=amount,
                    description=f"Sortie trésorerie – paiement {supplier_payment.supplier.name}",
                ),
            ])
        return entry

    # ── Utilitaires pour les rapports ─────────────────────────────────

    @staticmethod
    def get_trial_balance(exercise=None):
        """
        Retourne la balance générale : liste de comptes avec
        total_debit, total_credit, solde.
        """
        from django.db.models import Sum, Q

        accounts = Account.objects.filter(
            is_active=True, delete_at__isnull=True
        ).order_by('code')

        result = []
        for account in accounts:
            filters = {
                'entry__is_validated': True,
                'account': account,
                'delete_at__isnull': True,
            }
            if exercise:
                filters['entry__exercise'] = exercise

            totals = JournalEntryLine.objects.filter(**filters).aggregate(
                total_debit=Sum('debit'),
                total_credit=Sum('credit'),
            )
            total_debit = totals['total_debit'] or Decimal('0')
            total_credit = totals['total_credit'] or Decimal('0')
            balance = account.get_balance(exercise)

            if total_debit > 0 or total_credit > 0:
                result.append({
                    'account': account,
                    'total_debit': total_debit,
                    'total_credit': total_credit,
                    'balance': balance,
                })
        return result

    @staticmethod
    def get_general_ledger(account, exercise=None):
        """
        Retourne le grand livre pour un compte donné :
        liste des lignes d'écriture avec solde progressif.
        """
        filters = {
            'account': account,
            'entry__is_validated': True,
            'delete_at__isnull': True,
        }
        if exercise:
            filters['entry__exercise'] = exercise

        lines = (
            JournalEntryLine.objects
            .filter(**filters)
            .select_related('entry')
            .order_by('entry__date', 'entry__create_at')
        )

        result = []
        running_balance = Decimal('0')
        for line in lines:
            if account.account_type in ('ACTIF', 'CHARGE'):
                running_balance += line.debit - line.credit
            else:
                running_balance += line.credit - line.debit
            result.append({
                'line': line,
                'running_balance': running_balance,
            })
        return result

    # ══════════════════════════════════════════════════════════════════
    # Phase 3 — Rapports financiers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_income_statement(exercise=None):
        """
        Compte de résultat : produits − charges = résultat net.
        Retourne dict avec listes de charges/produits et totaux.
        """
        filters = {
            'entry__is_validated': True,
            'delete_at__isnull': True,
        }
        if exercise:
            filters['entry__exercise'] = exercise

        # Comptes de charges (classe 6)
        charges = Account.objects.filter(
            is_active=True, delete_at__isnull=True,
            code__startswith='6',
        ).order_by('code')

        charges_detail = []
        total_charges = Decimal('0')
        for account in charges:
            f = dict(filters)
            f['account'] = account
            totals = JournalEntryLine.objects.filter(**f).aggregate(
                total_debit=Coalesce(Sum('debit'), Value(Decimal('0'))),
                total_credit=Coalesce(Sum('credit'), Value(Decimal('0'))),
            )
            balance = totals['total_debit'] - totals['total_credit']
            if balance != 0:
                charges_detail.append({
                    'account': account,
                    'total_debit': totals['total_debit'],
                    'total_credit': totals['total_credit'],
                    'balance': balance,
                })
                total_charges += balance

        # Comptes de produits (classe 7)
        produits = Account.objects.filter(
            is_active=True, delete_at__isnull=True,
            code__startswith='7',
        ).order_by('code')

        produits_detail = []
        total_produits = Decimal('0')
        for account in produits:
            f = dict(filters)
            f['account'] = account
            totals = JournalEntryLine.objects.filter(**f).aggregate(
                total_debit=Coalesce(Sum('debit'), Value(Decimal('0'))),
                total_credit=Coalesce(Sum('credit'), Value(Decimal('0'))),
            )
            balance = totals['total_credit'] - totals['total_debit']
            if balance != 0:
                produits_detail.append({
                    'account': account,
                    'total_debit': totals['total_debit'],
                    'total_credit': totals['total_credit'],
                    'balance': balance,
                })
                total_produits += balance

        resultat_net = total_produits - total_charges

        return {
            'charges': charges_detail,
            'produits': produits_detail,
            'total_charges': total_charges,
            'total_produits': total_produits,
            'resultat_net': resultat_net,
            'is_benefice': resultat_net >= 0,
        }

    @staticmethod
    def get_balance_sheet(exercise=None):
        """
        Bilan comptable simplifié :
        ACTIF (classes 1–5 type ACTIF) = PASSIF (classes 1–5 type PASSIF)
        Le résultat de l'exercice est intégré côté passif.
        """
        filters = {
            'entry__is_validated': True,
            'delete_at__isnull': True,
        }
        if exercise:
            filters['entry__exercise'] = exercise

        def _get_accounts(account_type, code_prefixes):
            """Retourne les comptes avec leur solde."""
            result = []
            total = Decimal('0')
            for prefix in code_prefixes:
                accounts = Account.objects.filter(
                    is_active=True, delete_at__isnull=True,
                    account_type=account_type,
                    code__startswith=prefix,
                ).order_by('code')
                for account in accounts:
                    balance = account.get_balance(exercise)
                    if balance != 0:
                        result.append({
                            'account': account,
                            'balance': abs(balance),
                        })
                        total += abs(balance)
            return result, total

        # ACTIF
        actif_immobilise, total_immo = _get_accounts('ACTIF', ['2'])
        actif_circulant, total_circ = _get_accounts('ACTIF', ['3', '4'])
        tresorerie_actif, total_treso = _get_accounts('ACTIF', ['5'])
        total_actif = total_immo + total_circ + total_treso

        # PASSIF
        capitaux, total_capitaux = _get_accounts('PASSIF', ['1'])
        dettes, total_dettes = _get_accounts('PASSIF', ['4'])
        tresorerie_passif, total_treso_passif = _get_accounts('PASSIF', ['5'])

        # Résultat de l'exercice
        income = AccountingService.get_income_statement(exercise)
        resultat_net = income['resultat_net']

        total_passif = total_capitaux + total_dettes + total_treso_passif + max(resultat_net, Decimal('0'))

        return {
            'actif_immobilise': actif_immobilise,
            'actif_circulant': actif_circulant,
            'tresorerie_actif': tresorerie_actif,
            'total_immo': total_immo,
            'total_circ': total_circ,
            'total_treso': total_treso,
            'total_actif': total_actif,
            'capitaux': capitaux,
            'dettes': dettes,
            'tresorerie_passif': tresorerie_passif,
            'total_capitaux': total_capitaux,
            'total_dettes': total_dettes,
            'total_treso_passif': total_treso_passif,
            'resultat_net': resultat_net,
            'total_passif': total_passif,
        }

    @staticmethod
    def get_aged_balance(balance_type='client', exercise=None):
        """
        Balance âgée : créances clients ou dettes fournisseurs
        regroupées par tranche d'ancienneté.
        balance_type : 'client' ou 'supplier'
        """
        from core.models.sale_models import CreditSale
        from core.models.inventory_models import Supply

        today = date.today()
        tranches = [
            ('0-30', 0, 30),
            ('31-60', 31, 60),
            ('61-90', 61, 90),
            ('90+', 91, 9999),
        ]

        if balance_type == 'client':
            # Créances clients = CreditSale non fully paid
            items = CreditSale.objects.filter(
                is_fully_paid=False,
                delete_at__isnull=True,
            ).select_related('sale__client', 'sale__daily')

            result = []
            totals = {t[0]: Decimal('0') for t in tranches}
            grand_total = Decimal('0')

            for cs in items:
                remaining = Decimal(str(cs.amount_remaining or 0))
                if remaining <= 0:
                    continue
                sale_date = cs.sale.create_at.date() if cs.sale.create_at else today
                age_days = (today - sale_date).days

                tranche_key = '90+'
                for label, low, high in tranches:
                    if low <= age_days <= high:
                        tranche_key = label
                        break

                client_name = ''
                if cs.sale.client:
                    client_name = f"{cs.sale.client.firstname} {cs.sale.client.lastname}"

                result.append({
                    'reference': f"Vente #{cs.sale_id}",
                    'tiers': client_name or 'Client anonyme',
                    'date': sale_date,
                    'due_date': cs.due_date,
                    'age_days': age_days,
                    'tranche': tranche_key,
                    'amount': remaining,
                })
                totals[tranche_key] += remaining
                grand_total += remaining

            return {
                'items': result,
                'tranches_data': [
                    {'label': label, 'amount': totals[label]}
                    for label, _, _ in tranches
                ],
                'totals': totals,
                'grand_total': grand_total,
                'balance_type': 'client',
                'title': 'Créances clients',
            }
            return {
                'items': result,
                'totals': totals,
                'grand_total': grand_total,
                'tranches': [t[0] for t in tranches],
                'balance_type': 'client',
                'title': 'Créances clients',
            }

        else:  # supplier
            # Dettes fournisseurs : solde du compte 401
            account_401 = Account.objects.filter(code='401').first()
            balance_401 = account_401.get_balance(exercise) if account_401 else Decimal('0')

            # Détail des lignes d'écriture sur le 401
            filters = {
                'account': account_401,
                'entry__is_validated': True,
                'delete_at__isnull': True,
            }
            if exercise:
                filters['entry__exercise'] = exercise

            lines = JournalEntryLine.objects.filter(
                **filters
            ).select_related('entry').order_by('entry__date')

            result = []
            totals = {t[0]: Decimal('0') for t in tranches}
            grand_total = Decimal('0')

            for line in lines:
                net = line.credit - line.debit
                if net <= 0:
                    continue
                entry_date = line.entry.date
                age_days = (today - entry_date).days

                tranche_key = '90+'
                for label, low, high in tranches:
                    if low <= age_days <= high:
                        tranche_key = label
                        break

                result.append({
                    'reference': line.entry.reference,
                    'tiers': line.entry.description,
                    'date': entry_date,
                    'due_date': None,
                    'age_days': age_days,
                    'tranche': tranche_key,
                    'amount': net,
                })
                totals[tranche_key] += net
                grand_total += net

            return {
                'items': result,
                'tranches_data': [
                    {'label': label, 'amount': totals[label]}
                    for label, _, _ in tranches
                ],
                'totals': totals,
                'grand_total': grand_total,
                'balance_type': 'client',
                'title': 'Créances clients',
}
            return {
                'items': result,
                'totals': totals,
                'grand_total': grand_total,
                'tranches': [t[0] for t in tranches],
                'balance_type': 'supplier',
                'title': 'Dettes fournisseurs',
            }



    @staticmethod
    def get_product_margins(exercise=None):
        """
        Rapport de marge par produit :
        CA (chiffre d'affaires) − Coût d'achat = Marge brute
        """
        from core.models.sale_models import SaleProduct
        from core.models.product_models import Product

        products = Product.objects.filter(
            delete_at__isnull=True
        ).order_by('name')

        filters = {'sale__delete_at__isnull': True, 'delete_at__isnull': True}
        if exercise:
            filters['sale__daily__exercise'] = exercise

        result = []
        total_ca = Decimal('0')
        total_cost = Decimal('0')
        total_margin = Decimal('0')

        for product in products:
            sp_qs = SaleProduct.objects.filter(
                product=product, **filters
            )
            agg = sp_qs.aggregate(
                total_qty=Coalesce(Sum('quantity'), Value(0)),
                total_revenue=Coalesce(
                    Sum(F('quantity') * F('unit_price'), output_field=DecimalField()),
                    Value(Decimal('0')),
                ),
            )
            qty_sold = agg['total_qty']
            revenue = agg['total_revenue']

            if qty_sold == 0:
                continue

            # Coût d'achat = last_purchase_price × quantité vendue
            purchase_price = product.last_purchase_price or Decimal('0')
            cost = purchase_price * qty_sold
            margin = revenue - cost
            margin_pct = (margin / revenue * 100) if revenue else Decimal('0')

            result.append({
                'product': product,
                'qty_sold': qty_sold,
                'revenue': revenue,
                'purchase_price': purchase_price,
                'cost': cost,
                'margin': margin,
                'margin_pct': margin_pct,
            })
            total_ca += revenue
            total_cost += cost
            total_margin += margin

        # Trier par marge décroissante
        result.sort(key=lambda x: x['margin'], reverse=True)

        total_margin_pct = (total_margin / total_ca * 100) if total_ca else Decimal('0')

        return {
            'items': result,
            'total_ca': total_ca,
            'total_cost': total_cost,
            'total_margin': total_margin,
            'total_margin_pct': total_margin_pct,
        }

    # ── Déclaration TVA ──────────────────────────────────────────────

    @classmethod
    def get_vat_declaration(cls, exercise=None, date_start=None, date_end=None):
        """
        Génère la déclaration de TVA pour une période donnée.
        - TVA collectée  = somme des crédits sur le compte 4431
        - TVA déductible = somme des débits sur le compte 4451
        - TVA due        = TVA collectée − TVA déductible
        """
        filters = Q(entry__delete_at__isnull=True)
        if exercise:
            filters &= Q(entry__exercise=exercise)
        if date_start:
            filters &= Q(entry__date__gte=date_start)
        if date_end:
            filters &= Q(entry__date__lte=date_end)

        zero = Decimal('0')

        # TVA collectée (crédit 4431)
        tva_collectee = JournalEntryLine.objects.filter(
            filters, account__code='4431'
        ).aggregate(
            total=Coalesce(Sum('credit'), zero, output_field=DecimalField())
        )['total']

        # TVA déductible (débit 4451)
        tva_deductible = JournalEntryLine.objects.filter(
            filters, account__code='4451'
        ).aggregate(
            total=Coalesce(Sum('debit'), zero, output_field=DecimalField())
        )['total']

        tva_due = tva_collectee - tva_deductible

        # Détail par mois
        monthly = []
        lines_4431 = JournalEntryLine.objects.filter(
            filters, account__code='4431'
        ).values('entry__date__year', 'entry__date__month').annotate(
            collectee=Coalesce(Sum('credit'), zero, output_field=DecimalField())
        ).order_by('entry__date__year', 'entry__date__month')

        lines_4451 = JournalEntryLine.objects.filter(
            filters, account__code='4451'
        ).values('entry__date__year', 'entry__date__month').annotate(
            deductible=Coalesce(Sum('debit'), zero, output_field=DecimalField())
        ).order_by('entry__date__year', 'entry__date__month')

        # Construire un dict par (année, mois)
        deductible_map = {
            (r['entry__date__year'], r['entry__date__month']): r['deductible']
            for r in lines_4451
        }

        all_months = set()
        collectee_map = {}
        for r in lines_4431:
            key = (r['entry__date__year'], r['entry__date__month'])
            collectee_map[key] = r['collectee']
            all_months.add(key)
        for key in deductible_map:
            all_months.add(key)

        for year, month in sorted(all_months):
            c = collectee_map.get((year, month), zero)
            d = deductible_map.get((year, month), zero)
            monthly.append({
                'year': year,
                'month': month,
                'collectee': c,
                'deductible': d,
                'due': c - d,
            })

        return {
            'tva_collectee': tva_collectee,
            'tva_deductible': tva_deductible,
            'tva_due': tva_due,
            'monthly': monthly,
        }

    # ── Rapprochement bancaire ────────────────────────────────────────

    @classmethod
    def import_bank_statements(cls, account_code, lines):
        """
        Importe des lignes de relevé bancaire.
        `lines` = liste de dicts : {date, description, amount, type, reference?}
        Retourne le nombre de lignes importées.
        """
        from core.models.accounting_models import BankStatement
        account = cls.get_account(account_code)
        created = []
        for line in lines:
            created.append(BankStatement(
                account=account,
                statement_date=line['date'],
                description=line['description'],
                amount=Decimal(str(line['amount'])),
                statement_type=line['type'],  # CREDIT ou DEBIT
                reference=line.get('reference', ''),
            ))
        BankStatement.objects.bulk_create(created)
        return len(created)

    @classmethod
    def get_bank_reconciliation(cls, account_code, date_start=None, date_end=None):
        """
        Retourne les données pour le rapprochement bancaire :
        - Lignes de relevé (rapprochées et non rapprochées)
        - Écritures comptables correspondantes
        - Écarts éventuels
        """
        from core.models.accounting_models import BankStatement
        account = cls.get_account(account_code)

        # Relevés bancaires
        stmt_filters = Q(account=account, delete_at__isnull=True)
        if date_start:
            stmt_filters &= Q(statement_date__gte=date_start)
        if date_end:
            stmt_filters &= Q(statement_date__lte=date_end)

        statements = BankStatement.objects.filter(stmt_filters).order_by('statement_date')

        # Écritures comptables sur ce compte
        entry_filters = Q(account=account, entry__delete_at__isnull=True)
        if date_start:
            entry_filters &= Q(entry__date__gte=date_start)
        if date_end:
            entry_filters &= Q(entry__date__lte=date_end)

        entries = JournalEntryLine.objects.filter(entry_filters).select_related(
            'entry'
        ).order_by('entry__date')

        zero = Decimal('0')

        # Solde relevé
        solde_releve = statements.aggregate(
            credits=Coalesce(
                Sum('amount', filter=Q(statement_type='CREDIT')),
                zero, output_field=DecimalField()
            ),
            debits=Coalesce(
                Sum('amount', filter=Q(statement_type='DEBIT')),
                zero, output_field=DecimalField()
            ),
        )
        solde_banque = solde_releve['credits'] - solde_releve['debits']

        # Solde comptable
        solde_comptable_data = entries.aggregate(
            total_debit=Coalesce(Sum('debit'), zero, output_field=DecimalField()),
            total_credit=Coalesce(Sum('credit'), zero, output_field=DecimalField()),
        )
        solde_comptable = solde_comptable_data['total_debit'] - solde_comptable_data['total_credit']

        # Non rapprochés
        non_reconciled_stmts = statements.filter(is_reconciled=False)
        reconciled_entry_ids = statements.filter(
            is_reconciled=True, reconciled_entry__isnull=False
        ).values_list('reconciled_entry_id', flat=True)
        non_reconciled_entries = entries.exclude(id__in=reconciled_entry_ids)

        return {
            'account': account,
            'statements': statements,
            'entries': entries,
            'solde_banque': solde_banque,
            'solde_comptable': solde_comptable,
            'ecart': solde_banque - solde_comptable,
            'non_reconciled_statements': non_reconciled_stmts,
            'non_reconciled_entries': non_reconciled_entries,
            'nb_reconciled': statements.filter(is_reconciled=True).count(),
            'nb_total': statements.count(),
        }

    @classmethod
    def reconcile_statement(cls, statement_id, entry_line_id, user=None):
        """
        Rapproche une ligne de relevé bancaire avec une ligne d'écriture comptable.
        """
        from core.models.accounting_models import BankStatement
        stmt = BankStatement.objects.get(id=statement_id, delete_at__isnull=True)
        entry_line = JournalEntryLine.objects.get(id=entry_line_id)

        stmt.is_reconciled = True
        stmt.reconciled_entry = entry_line
        stmt.reconciled_at = timezone.now()
        stmt.reconciled_by = user
        stmt.save()
        return stmt

    @classmethod
    def unreconcile_statement(cls, statement_id):
        """Annule le rapprochement d'une ligne de relevé."""
        from core.models.accounting_models import BankStatement
        stmt = BankStatement.objects.get(id=statement_id, delete_at__isnull=True)
        stmt.is_reconciled = False
        stmt.reconciled_entry = None
        stmt.reconciled_at = None
        stmt.reconciled_by = None
        stmt.save()
        return stmt

    # ── Clôture d'exercice ───────────────────────────────────────────

    @classmethod
    def close_exercise(cls, exercise, user=None):
        """
        Clôture un exercice comptable :
        1. Calcule le résultat (Produits classe 7 − Charges classe 6)
        2. Solde les comptes 6 et 7 vers le compte 12 (Résultat de l'exercice)
        3. Ferme l'exercice (end_date = now)
        4. Enregistre l'historique dans ExerciseClosing
        Retourne l'objet ExerciseClosing créé.
        """
        from core.models.accounting_models import ExerciseClosing

        if not exercise.is_active():
            raise ValueError("Cet exercice est déjà clôturé.")

        zero = Decimal('0')

        with transaction.atomic():
            # Calculer soldes des classes 6 et 7
            accounts_6 = Account.objects.filter(
                code__startswith='6', delete_at__isnull=True
            )
            accounts_7 = Account.objects.filter(
                code__startswith='7', delete_at__isnull=True
            )

            total_charges = zero
            total_produits = zero
            closing_lines = []

            # Classe 6 - Charges (solde = debit - credit)
            for acc in accounts_6:
                balance = acc.get_balance(exercise)
                if balance != zero:
                    total_charges += balance
                    # Solder : écriture inverse (crédit pour solder un solde débiteur)
                    if balance > 0:
                        closing_lines.append({'account': acc, 'debit': zero, 'credit': balance})
                    else:
                        closing_lines.append({'account': acc, 'debit': abs(balance), 'credit': zero})

            # Classe 7 - Produits (solde = credit - debit)
            for acc in accounts_7:
                balance = acc.get_balance(exercise)
                if balance != zero:
                    total_produits += balance
                    # Solder : écriture inverse (débit pour solder un solde créditeur)
                    if balance > 0:
                        closing_lines.append({'account': acc, 'debit': balance, 'credit': zero})
                    else:
                        closing_lines.append({'account': acc, 'debit': zero, 'credit': abs(balance)})

            resultat = total_produits - total_charges

            # Écriture de clôture
            ref = cls._generate_reference('CL')
            closing_entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Clôture exercice {exercise} — Résultat: {resultat} FCFA",
                journal='OD',  # Opérations diverses
                exercise=exercise,
                is_validated=True,
            )

            # Lignes de solde des comptes 6 et 7
            entry_lines = []
            for line in closing_lines:
                entry_lines.append(JournalEntryLine(
                    entry=closing_entry,
                    account=line['account'],
                    debit=line['debit'],
                    credit=line['credit'],
                    description=f"Clôture {line['account'].code} — {line['account'].name}",
                ))

            # Ligne résultat vers compte 12
            compte_12 = cls.get_account('12')
            if resultat >= 0:
                # Bénéfice → Crédit 12
                entry_lines.append(JournalEntryLine(
                    entry=closing_entry,
                    account=compte_12,
                    debit=zero, credit=resultat,
                    description=f"Résultat de l'exercice (bénéfice)",
                ))
            else:
                # Perte → Débit 12
                entry_lines.append(JournalEntryLine(
                    entry=closing_entry,
                    account=compte_12,
                    debit=abs(resultat), credit=zero,
                    description=f"Résultat de l'exercice (perte)",
                ))

            JournalEntryLine.objects.bulk_create(entry_lines)

            # Fermer l'exercice
            exercise.end_date = timezone.now()
            exercise.save()

            # Historique
            closing = ExerciseClosing.objects.create(
                exercise=exercise,
                closed_at=timezone.now(),
                closed_by=user,
                result_amount=resultat,
                closing_entry=closing_entry,
            )

        return closing

    @classmethod
    def open_new_exercise(cls, closing, user=None):
        """
        Ouvre un nouvel exercice avec report à nouveau des comptes de bilan (classes 1-5).
        1. Crée un nouvel exercice
        2. Crée une écriture d'ouverture avec les soldes des comptes 1-5
        3. Reporte le résultat (compte 12) vers le report à nouveau (131/139)
        Retourne le nouvel exercice créé.
        """
        from core.models.accounting_models import Exercise

        old_exercise = closing.exercise
        zero = Decimal('0')

        with transaction.atomic():
            # Créer le nouvel exercice
            new_exercise = Exercise.objects.create(
                start_date=timezone.now(),
                end_date=None,
            )

            # Écriture d'ouverture (report à nouveau)
            ref = cls._generate_reference('AN')  # À-Nouveau
            opening_entry = JournalEntry.objects.create(
                reference=ref,
                date=timezone.now().date(),
                description=f"Report à nouveau — ouverture exercice {new_exercise}",
                journal='AN',
                exercise=new_exercise,
                is_validated=True,
            )

            entry_lines = []

            # Reporter les soldes des comptes de bilan (classes 1-5)
            bilan_accounts = Account.objects.filter(
                delete_at__isnull=True
            ).exclude(
                code__startswith='6'
            ).exclude(
                code__startswith='7'
            ).order_by('code')

            for acc in bilan_accounts:
                balance = acc.get_balance(old_exercise)
                if balance == zero:
                    continue

                if acc.account_type in ('ACTIF', 'CHARGE'):
                    # Solde normalement débiteur
                    if balance > 0:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=balance, credit=zero,
                            description=f"Report à nouveau {acc.code}",
                        ))
                    else:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=zero, credit=abs(balance),
                            description=f"Report à nouveau {acc.code}",
                        ))
                else:
                    # PASSIF/PRODUIT — solde normalement créditeur
                    if balance > 0:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=zero, credit=balance,
                            description=f"Report à nouveau {acc.code}",
                        ))
                    else:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=abs(balance), credit=zero,
                            description=f"Report à nouveau {acc.code}",
                        ))

            # Reporter le résultat (12) vers report à nouveau (131 ou 139)
            resultat = closing.result_amount
            if resultat > 0:
                # Bénéfice → vider 12 (débit) → 131 (crédit)
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('12'),
                    debit=resultat, credit=zero,
                    description="Affectation résultat bénéficiaire",
                ))
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('131'),
                    debit=zero, credit=resultat,
                    description="Report à nouveau — bénéfice",
                ))
            elif resultat < 0:
                # Perte → vider 12 (crédit) → 139 (débit)
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('12'),
                    debit=zero, credit=abs(resultat),
                    description="Affectation résultat déficitaire",
                ))
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('139'),
                    debit=abs(resultat), credit=zero,
                    description="Report à nouveau — perte",
                ))

            if entry_lines:
                JournalEntryLine.objects.bulk_create(entry_lines)

            # Mettre à jour le closing
            closing.opening_entry = opening_entry
            closing.new_exercise = new_exercise
            closing.save()

        return new_exercise
