"""
Service comptable : initialisation du plan comptable OHADA et génération
automatique des écritures comptables (partie double).
"""

from datetime import date, timedelta
from decimal import Decimal

import logging

from django.db import IntegrityError, transaction
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_noop

from core.models.accounting_models import (
    Account, JournalEntry, JournalEntryLine,
    PAYMENT_METHOD_ACCOUNT_MAP, TaxRate,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Plan comptable OHADA simplifié (comptes les plus courants pour le commerce)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_ACCOUNTS = [
    # Classe 1 – Capitaux propres
    ('12', gettext_noop('Résultat de l\'exercice'), 'PASSIF', None),
    ('13', gettext_noop('Report à nouveau'), 'PASSIF', None),
    ('131', gettext_noop('Report à nouveau (solde créditeur)'), 'PASSIF', '13'),
    ('139', gettext_noop('Report à nouveau (solde débiteur)'), 'ACTIF', '13'),
    # Classe 3 – Stocks
    ('31', gettext_noop('Stocks de marchandises'), 'ACTIF', None),
    # Classe 4 – Tiers
    ('401', gettext_noop('Fournisseurs'), 'PASSIF', None),
    ('411', gettext_noop('Clients'), 'ACTIF', None),
    ('443', gettext_noop('État, TVA facturée'), 'PASSIF', None),
    ('4431', gettext_noop('TVA facturée sur ventes'), 'PASSIF', '443'),
    ('445', gettext_noop('État, TVA récupérable'), 'ACTIF', None),
    ('4451', gettext_noop('TVA récupérable sur achats'), 'ACTIF', '445'),
    ('4441', gettext_noop('État, TVA due'), 'PASSIF', None),
    # Classe 5 – Trésorerie
    ('52', gettext_noop('Banques'), 'ACTIF', None),
    ('521', gettext_noop('Banque locale'), 'ACTIF', '52'),
    ('57', gettext_noop('Caisse'), 'ACTIF', None),
    ('571', gettext_noop('Caisse principale'), 'ACTIF', '57'),
    ('58', gettext_noop('Virements internes'), 'ACTIF', None),
    ('585', gettext_noop('Mobile Money'), 'ACTIF', '58'),
    # Classe 6 – Charges
    ('601', gettext_noop("Achats de marchandises"), 'CHARGE', None),
    ('6031', gettext_noop("Variations de stocks de marchandises"), 'CHARGE', None),
    ('61', gettext_noop("Transports"), 'CHARGE', None),
    ('62', gettext_noop("Services extérieurs"), 'CHARGE', None),
    ('63', gettext_noop("Autres services extérieurs"), 'CHARGE', None),
    ('64', gettext_noop("Charges de personnel"), 'CHARGE', None),
    ('65', gettext_noop("Autres charges"), 'CHARGE', None),
    # Classe 7 – Produits
    ('701', gettext_noop('Ventes de marchandises'), 'PRODUIT', None),
    ('71', gettext_noop("Production stockée"), 'PRODUIT', None),
    ('75', gettext_noop('Autres produits'), 'PRODUIT', None),
    ('758', gettext_noop('Produits divers'), 'PRODUIT', None),
]


class AccountingService:
    """Service principal pour la comptabilité."""

    # ── Initialisation du plan comptable ──────────────────────────────

    @staticmethod
    def init_chart_of_accounts(using=None):
        """
        Initialise le plan comptable OHADA avec les comptes par défaut.
        Ne crée que les comptes manquants (idempotent).
        Retourne le nombre de comptes créés.

        ``using`` désigne la base à peupler. Il est indispensable en
        multi-base : ``migrate --database=<alias>`` transmet l'alias migré
        au signal ``post_migrate``, et sans lui le seed irait dans la base
        par défaut au lieu de celle qui vient d'être créée.
        La résolution du parent doit viser la MÊME base, sinon un compte
        serait rattaché au parent d'une autre société.
        ``using=None`` laisse le routeur décider (comportement mono-base).
        """
        created_count = 0
        for code, name, account_type, parent_code in DEFAULT_ACCOUNTS:
            parent_id = None
            if parent_code:
                # On ne récupère que l'identifiant : affecter l'OBJET parent
                # ferait passer l'affectation par le routeur de bases, qui,
                # hors contexte société (cas d'un `migrate --database=...`),
                # rattacherait la nouvelle ligne à la mauvaise base.
                parent_id = Account.objects.db_manager(using).filter(
                    code=parent_code
                ).values_list('pk', flat=True).first()
            _unused, created = Account.objects.db_manager(using).get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'account_type': account_type,
                    'parent_id': parent_id,
                },
            )
            if created:
                created_count += 1
        return created_count

    # ── Génération de référence unique ────────────────────────────────

    @staticmethod
    def _generate_reference(journal_code: str) -> str:
        """Génère la prochaine référence du jour : VE-20260225-001"""
        today = date.today().strftime('%Y%m%d')
        prefix = f"{journal_code}-{today}-"
        # Max numérique (et non lexicographique : '999' > '1000' sinon)
        seq = 0
        for ref in JournalEntry.objects.filter(
            reference__startswith=prefix
        ).values_list('reference', flat=True):
            suffix = ref[len(prefix):]
            if suffix.isdigit():
                seq = max(seq, int(suffix))
        return f"{prefix}{seq + 1:03d}"

    _REFERENCE_RETRIES = 5

    @classmethod
    def _create_entry(cls, journal_code: str, **fields) -> JournalEntry:
        """
        Crée une écriture avec une référence unique. La numérotation n'étant
        pas verrouillée, deux écritures simultanées peuvent calculer la même
        référence : on réessaie dans un savepoint sur ``IntegrityError``.
        """
        last_error = None
        for _unused in range(cls._REFERENCE_RETRIES):
            ref = cls._generate_reference(journal_code)
            try:
                with transaction.atomic():
                    return JournalEntry.objects.create(reference=ref, **fields)
            except IntegrityError as exc:
                last_error = exc
        raise last_error

    # ── Helpers pour récupérer un compte ──────────────────────────────

    @staticmethod
    def get_account(code: str) -> Account:
        """Récupère un compte actif par son code. Lève DoesNotExist si absent/inactif."""
        return Account.objects.get(code=code, is_active=True, delete_at__isnull=True)

    @staticmethod
    def treasury_account_code(payment_method) -> str:
        """
        Code du compte de trésorerie pour un mode de paiement.
        Un mode inconnu lève une erreur au lieu de retomber silencieusement
        sur la caisse (571).
        """
        if not payment_method:
            return PAYMENT_METHOD_ACCOUNT_MAP['CASH']
        try:
            return PAYMENT_METHOD_ACCOUNT_MAP[payment_method]
        except KeyError:
            raise ValueError(_("Mode de paiement inconnu : %(method)s") % {'method': payment_method})

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

    @classmethod
    def record_sale_cancellation(
        cls,
        sale,
        daily,
        exercise,
        refund_payment_method='CASH',
        refund_amount=None,
    ):
        """
        Enregistre les écritures d'annulation d'une vente.

        - Vente comptant : contrepassation directe avec sortie de trésorerie.
        - Vente à crédit : contrepassation sur 411, puis remboursement séparé
          du montant déjà encaissé le cas échéant.
        """
        amount = Decimal(str(sale.total or 0))
        if amount <= 0:
            return []

        if refund_amount is None:
            refund_amount = amount if not getattr(sale, 'is_credit', False) else Decimal('0')
        refund_amount = Decimal(str(refund_amount or 0))

        recognized_tva = bool(getattr(sale, 'has_vat', False) and getattr(sale, 'tva_accounting_created', False))
        tax_rate = cls.get_default_tax_rate() if recognized_tva else None
        revenue_amount, tva_amount = cls.compute_tax(amount, tax_rate)

        entries = []

        with transaction.atomic():
            reversal_entry = cls._create_entry(
                'VE',
                date=timezone.now().date(),
                description=_("Annulation vente #%(id)s") % {'id': sale.id},
                journal='VE',
                exercise=exercise,
                daily=daily,
                sale=sale,
            )

            reversal_lines = [
                JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('701'),
                    debit=revenue_amount,
                    credit=0,
                    description=_("Contrepassation vente #%(id)s") % {'id': sale.id},
                ),
            ]

            if tva_amount > 0:
                reversal_lines.append(JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('4431'),
                    debit=tva_amount,
                    credit=0,
                    description=_("Contrepassation TVA collectée – vente #%(id)s") % {'id': sale.id},
                ))

            if getattr(sale, 'is_credit', False):
                credit_account = cls.get_account('411')
                credit_desc = _("Annulation créance client – vente #%(id)s") % {'id': sale.id}
            else:
                account_code = cls.treasury_account_code(refund_payment_method)
                credit_account = cls.get_account(account_code)
                credit_desc = _("Remboursement client – vente #%(id)s") % {'id': sale.id}

            reversal_lines.append(JournalEntryLine(
                entry=reversal_entry,
                account=credit_account,
                debit=0,
                credit=amount,
                description=credit_desc,
            ))
            JournalEntryLine.objects.bulk_create(reversal_lines)
            entries.append(reversal_entry)

            if getattr(sale, 'is_credit', False) and refund_amount > 0:
                refund_entry = cls._create_entry(
                    'CA',
                    date=timezone.now().date(),
                    description=_("Remboursement client – annulation vente #%(id)s") % {'id': sale.id},
                    journal='CA',
                    exercise=exercise,
                    daily=daily,
                    sale=sale,
                )
                account_code = cls.treasury_account_code(refund_payment_method)
                JournalEntryLine.objects.bulk_create([
                    JournalEntryLine(
                        entry=refund_entry,
                        account=cls.get_account('411'),
                        debit=refund_amount,
                        credit=0,
                        description=_("Extinction avoir client – vente #%(id)s") % {'id': sale.id},
                    ),
                    JournalEntryLine(
                        entry=refund_entry,
                        account=cls.get_account(account_code),
                        debit=0,
                        credit=refund_amount,
                        description=_("Sortie trésorerie – vente #%(id)s") % {'id': sale.id},
                    ),
                ])
                entries.append(refund_entry)

        return entries

    @classmethod
    def record_partial_sale_return(
        cls,
        sale,
        amount,
        daily,
        exercise,
        refund_payment_method='CASH',
        refund_amount=None,
    ):
        """Enregistre les écritures d'un retour partiel de vente."""
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return []

        refund_amount = Decimal(str(refund_amount or 0))
        recognized_tva = bool(getattr(sale, 'has_vat', False) and getattr(sale, 'tva_accounting_created', False))
        tax_rate = cls.get_default_tax_rate() if recognized_tva else None
        revenue_amount, tva_amount = cls.compute_tax(amount, tax_rate)

        entries = []

        with transaction.atomic():
            reversal_entry = cls._create_entry(
                'VE',
                date=timezone.now().date(),
                description=_("Retour partiel vente #%(id)s") % {'id': sale.id},
                journal='VE',
                exercise=exercise,
                daily=daily,
                sale=sale,
            )

            reversal_lines = [
                JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('701'),
                    debit=revenue_amount,
                    credit=0,
                    description=_("Contrepassation retour partiel – vente #%(id)s") % {'id': sale.id},
                ),
            ]

            if tva_amount > 0:
                reversal_lines.append(JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('4431'),
                    debit=tva_amount,
                    credit=0,
                    description=_("Contrepassation TVA – retour partiel vente #%(id)s") % {'id': sale.id},
                ))

            if getattr(sale, 'is_credit', False):
                credit_account = cls.get_account('411')
                credit_desc = _("Réduction créance client – vente #%(id)s") % {'id': sale.id}
            else:
                account_code = cls.treasury_account_code(refund_payment_method)
                credit_account = cls.get_account(account_code)
                credit_desc = _("Remboursement client – retour partiel vente #%(id)s") % {'id': sale.id}

            reversal_lines.append(JournalEntryLine(
                entry=reversal_entry,
                account=credit_account,
                debit=0,
                credit=amount,
                description=credit_desc,
            ))
            JournalEntryLine.objects.bulk_create(reversal_lines)
            entries.append(reversal_entry)

            if getattr(sale, 'is_credit', False) and refund_amount > 0:
                refund_entry = cls._create_entry(
                    'CA',
                    date=timezone.now().date(),
                    description=_("Remboursement client – retour partiel vente #%(id)s") % {'id': sale.id},
                    journal='CA',
                    exercise=exercise,
                    daily=daily,
                    sale=sale,
                )
                account_code = cls.treasury_account_code(refund_payment_method)
                JournalEntryLine.objects.bulk_create([
                    JournalEntryLine(
                        entry=refund_entry,
                        account=cls.get_account('411'),
                        debit=refund_amount,
                        credit=0,
                        description=_("Extinction avoir client – retour partiel vente #%(id)s") % {'id': sale.id},
                    ),
                    JournalEntryLine(
                        entry=refund_entry,
                        account=cls.get_account(account_code),
                        debit=0,
                        credit=refund_amount,
                        description=_("Sortie trésorerie – retour partiel vente #%(id)s") % {'id': sale.id},
                    ),
                ])
                entries.append(refund_entry)

        return entries

    @classmethod
    def record_supply_cancellation(
        cls,
        supply,
        daily,
        exercise,
        refund_payment_method='CASH',
        refund_amount=None,
    ):
        """
        Enregistre les écritures d'annulation d'un approvisionnement.

        - Achat comptant : contrepassation directe avec entrée de trésorerie.
        - Achat à crédit : réduction de la dette fournisseur sur 401, puis
          remboursement séparé du montant déjà payé le cas échéant.
        """
        amount = Decimal(str(supply.total_price or 0))
        if amount <= 0:
            return []

        if refund_amount is None:
            refund_amount = amount if not getattr(supply, 'is_credit', False) else Decimal('0')
        refund_amount = Decimal(str(refund_amount or 0))

        tax_rate = getattr(supply, 'tax_rate', None)
        purchase_amount, tva_amount = cls.compute_tax(amount, tax_rate)

        entries = []

        with transaction.atomic():
            reversal_entry = cls._create_entry(
                'AC',
                date=timezone.now().date(),
                description=_("Annulation approvisionnement #%(id)s") % {'id': supply.id},
                journal='AC',
                exercise=exercise,
                daily=daily,
                supply=supply,
            )

            reversal_lines = [
                JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('601'),
                    debit=0,
                    credit=purchase_amount,
                    description=_("Contrepassation achat – appro. #%(id)s") % {'id': supply.id},
                ),
            ]

            if tva_amount > 0:
                reversal_lines.append(JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('4451'),
                    debit=0,
                    credit=tva_amount,
                    description=_("Contrepassation TVA déductible – appro. #%(id)s") % {'id': supply.id},
                ))

            if getattr(supply, 'is_credit', False):
                debit_account = cls.get_account('401')
                debit_desc = _("Annulation dette fournisseur – appro. #%(id)s") % {'id': supply.id}
            else:
                account_code = cls.treasury_account_code(refund_payment_method)
                debit_account = cls.get_account(account_code)
                debit_desc = _("Remboursement fournisseur – appro. #%(id)s") % {'id': supply.id}

            reversal_lines.append(JournalEntryLine(
                entry=reversal_entry,
                account=debit_account,
                debit=amount,
                credit=0,
                description=debit_desc,
            ))
            JournalEntryLine.objects.bulk_create(reversal_lines)
            entries.append(reversal_entry)

            if getattr(supply, 'is_credit', False) and refund_amount > 0:
                reimbursement_entry = cls._create_entry(
                    'CA',
                    date=timezone.now().date(),
                    description=_("Remboursement fournisseur – annulation approvisionnement #%(id)s") % {'id': supply.id},
                    journal='CA',
                    exercise=exercise,
                    daily=daily,
                    supply=supply,
                )
                account_code = cls.treasury_account_code(refund_payment_method)
                JournalEntryLine.objects.bulk_create([
                    JournalEntryLine(
                        entry=reimbursement_entry,
                        account=cls.get_account(account_code),
                        debit=refund_amount,
                        credit=0,
                        description=_("Entrée trésorerie – appro. #%(id)s") % {'id': supply.id},
                    ),
                    JournalEntryLine(
                        entry=reimbursement_entry,
                        account=cls.get_account('401'),
                        debit=0,
                        credit=refund_amount,
                        description=_("Extinction avoir fournisseur – appro. #%(id)s") % {'id': supply.id},
                    ),
                ])
                entries.append(reimbursement_entry)

        return entries

    @classmethod
    def record_partial_supply_return(
        cls,
        supply,
        amount,
        daily,
        exercise,
        refund_payment_method='CASH',
        refund_amount=None,
    ):
        """Enregistre les écritures d'un retour partiel fournisseur."""
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return []

        refund_amount = Decimal(str(refund_amount or 0))
        tax_rate = getattr(supply, 'tax_rate', None)
        purchase_amount, tva_amount = cls.compute_tax(amount, tax_rate)

        entries = []

        with transaction.atomic():
            reversal_entry = cls._create_entry(
                'AC',
                date=timezone.now().date(),
                description=_("Retour partiel approvisionnement #%(id)s") % {'id': supply.id},
                journal='AC',
                exercise=exercise,
                daily=daily,
                supply=supply,
            )

            reversal_lines = [
                JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('601'),
                    debit=0,
                    credit=purchase_amount,
                    description=_("Contrepassation retour partiel – appro. #%(id)s") % {'id': supply.id},
                ),
            ]

            if tva_amount > 0:
                reversal_lines.append(JournalEntryLine(
                    entry=reversal_entry,
                    account=cls.get_account('4451'),
                    debit=0,
                    credit=tva_amount,
                    description=_("Contrepassation TVA – retour partiel appro. #%(id)s") % {'id': supply.id},
                ))

            if getattr(supply, 'is_credit', False):
                debit_account = cls.get_account('401')
                debit_desc = _("Réduction dette fournisseur – appro. #%(id)s") % {'id': supply.id}
            else:
                account_code = cls.treasury_account_code(refund_payment_method)
                debit_account = cls.get_account(account_code)
                debit_desc = _("Remboursement fournisseur – retour partiel appro. #%(id)s") % {'id': supply.id}

            reversal_lines.append(JournalEntryLine(
                entry=reversal_entry,
                account=debit_account,
                debit=amount,
                credit=0,
                description=debit_desc,
            ))
            JournalEntryLine.objects.bulk_create(reversal_lines)
            entries.append(reversal_entry)

            if getattr(supply, 'is_credit', False) and refund_amount > 0:
                reimbursement_entry = cls._create_entry(
                    'CA',
                    date=timezone.now().date(),
                    description=_("Remboursement fournisseur – retour partiel approvisionnement #%(id)s") % {'id': supply.id},
                    journal='CA',
                    exercise=exercise,
                    daily=daily,
                    supply=supply,
                )
                account_code = cls.treasury_account_code(refund_payment_method)
                JournalEntryLine.objects.bulk_create([
                    JournalEntryLine(
                        entry=reimbursement_entry,
                        account=cls.get_account(account_code),
                        debit=refund_amount,
                        credit=0,
                        description=_("Entrée trésorerie – retour partiel appro. #%(id)s") % {'id': supply.id},
                    ),
                    JournalEntryLine(
                        entry=reimbursement_entry,
                        account=cls.get_account('401'),
                        debit=0,
                        credit=refund_amount,
                        description=_("Extinction avoir fournisseur – retour partiel appro. #%(id)s") % {'id': supply.id},
                    ),
                ])
                entries.append(reimbursement_entry)

        return entries

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

        if is_credit and tax_rate:
            description = _("Vente #%(id)s (crédit) TVA %(rate)s%%") % {
                'id': sale.id, 'rate': tax_rate.rate,
            }
        elif is_credit:
            description = _("Vente #%(id)s (crédit)") % {'id': sale.id}
        elif tax_rate:
            description = _("Vente #%(id)s TVA %(rate)s%%") % {'id': sale.id, 'rate': tax_rate.rate}
        else:
            description = _("Vente #%(id)s") % {'id': sale.id}

        with transaction.atomic():
            entry = cls._create_entry(
                'VE',
                date=timezone.now().date(),
                description=description,
                journal='VE',
                exercise=exercise,
                daily=daily,
                sale=sale,
            )

            if is_credit:
                debit_account = cls.get_account('411')
                debit_desc = _("Créance client – vente #%(id)s") % {'id': sale.id}
            else:
                account_code = cls.treasury_account_code(payment_method)
                debit_account = cls.get_account(account_code)
                debit_desc = _("Encaissement vente #%(id)s") % {'id': sale.id}

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
                    description=_("Vente de marchandises #%(id)s (HT)") % {'id': sale.id},
                ),
            ]

            if tva > 0:
                lines.append(JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('4431'),
                    debit=0, credit=tva,
                    description=_("TVA collectée – vente #%(id)s") % {'id': sale.id},
                ))

            JournalEntryLine.objects.bulk_create(lines)
            if tva > 0 and not getattr(sale, 'tva_accounting_created', False):
                sale.tva_accounting_created = True
                sale.save(update_fields=['tva_accounting_created'])
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
        
        for sale in sales_with_tva:
            # Savepoint PAR vente : une erreur n'annule pas les autres et
            # n'aborte pas la transaction englobante.
            try:
                with transaction.atomic():
                    amount = Decimal(str(sale.total or 0))
                    if amount <= 0:
                        continue
                        
                    ht, tva = cls.compute_tax(amount, tax_rate)
                    
                    if tva <= 0:
                        continue
                    
                    # Créer une écriture de TVA collectée
                    entry = cls._create_entry(
                        'VE',
                        date=timezone.now().date(),
                        description=_("TVA collectée - Vente #%(id)s (clôture daily)") % {'id': sale.id},
                        journal='VE',
                        exercise=daily.exercise,
                        daily=daily,
                        sale=sale,
                    )
                    
                    JournalEntryLine.objects.bulk_create([
                        JournalEntryLine(
                            entry=entry,
                            account=cls.get_account('701'),
                            debit=tva,
                            credit=0,
                            description=_("Constatation TVA différée – vente #%(id)s") % {'id': sale.id},
                        ),
                        JournalEntryLine(
                            entry=entry,
                            account=cls.get_account('4431'),
                            debit=0,
                            credit=tva,
                            description=_("TVA collectée – vente #%(id)s") % {'id': sale.id},
                        ),
                    ])
                    
                    # Marquer la vente comme ayant ses écritures TVA créées
                    sale.tva_accounting_created = True
                    sale.save(update_fields=['tva_accounting_created'])
                    
                    entries_created += 1
                    
            except Exception:
                # Journaliser et continuer avec les autres ventes
                logger.exception(
                    "Écritures TVA différée impossibles pour la vente #%s", sale.id,
                )
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

        if is_credit and tax_rate:
            description = _("Approvisionnement #%(id)s – %(product)s (crédit) TVA %(rate)s%%") % {
                'id': supply.id, 'product': supply.product.name, 'rate': tax_rate.rate,
            }
        elif is_credit:
            description = _("Approvisionnement #%(id)s – %(product)s (crédit)") % {
                'id': supply.id, 'product': supply.product.name,
            }
        elif tax_rate:
            description = _("Approvisionnement #%(id)s – %(product)s TVA %(rate)s%%") % {
                'id': supply.id, 'product': supply.product.name, 'rate': tax_rate.rate,
            }
        else:
            description = _("Approvisionnement #%(id)s – %(product)s") % {
                'id': supply.id, 'product': supply.product.name,
            }

        with transaction.atomic():
            entry = cls._create_entry(
                'AC',
                date=timezone.now().date(),
                description=description,
                journal='AC',
                exercise=exercise,
                daily=daily,
                supply=supply,
            )

            if is_credit:
                credit_account = cls.get_account('401')
                credit_desc = _("Dette fournisseur – appro. #%(id)s") % {'id': supply.id}
            else:
                account_code = cls.treasury_account_code(payment_method)
                credit_account = cls.get_account(account_code)
                credit_desc = _("Paiement fournisseur – appro. #%(id)s") % {'id': supply.id}

            lines = [
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('601'),
                    debit=ht, credit=0,
                    description=_("Achat %(product)s (HT)") % {'product': supply.product.name},
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
                    description=_("TVA déductible – appro. #%(id)s") % {'id': supply.id},
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

        account_code = cls.treasury_account_code(payment_method)
        
        # Utiliser le compte sélectionné dans la dépense ou défaut 65.
        # Une dépense ne peut débiter qu'un compte de charge (classe 6) : cela
        # empêche d'effacer une créance (411) ou de créer un mouvement de
        # caisse fictif (571) via le module dépenses.
        if expense.account:
            expense_account = expense.account
            if not str(expense_account.code).startswith('6'):
                raise ValueError(
                    _("Une dépense doit être imputée sur un compte de charge (classe 6), "
                      "pas sur %(code)s.") % {'code': expense_account.code}
                )
        else:
            expense_account = cls.get_account('65')

        with transaction.atomic():
            entry = cls._create_entry(
                'CA',
                date=timezone.now().date(),
                description=_("Dépense – %(type)s") % {
                    'type': expense.expense_type.name if expense.expense_type else _('Divers'),
                },
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
                    description=expense.description or _("Dépense #%(id)s") % {'id': expense.id},
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=0, credit=amount,
                    description=_("Sortie de caisse – dépense #%(id)s") % {'id': expense.id},
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

        account_code = cls.treasury_account_code(payment_method)
        
        # Utiliser le compte sélectionné dans la recette ou défaut 75.
        # Une recette ne peut créditer qu'un compte de produit (classe 7).
        if recipe.account:
            recipe_account = recipe.account
            if not str(recipe_account.code).startswith('7'):
                raise ValueError(
                    _("Une recette doit être imputée sur un compte de produit (classe 7), "
                      "pas sur %(code)s.") % {'code': recipe_account.code}
                )
        else:
            recipe_account = cls.get_account('75')

        with transaction.atomic():
            entry = cls._create_entry(
                'CA',
                date=timezone.now().date(),
                description=_("Recette – %(type)s") % {
                    'type': recipe.recipe_type.name if recipe.recipe_type else _('Divers'),
                },
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=amount, credit=0,
                    description=_("Entrée de caisse – recette #%(id)s") % {'id': recipe.id},
                ),
                JournalEntryLine(
                    entry=entry,
                    account=recipe_account,
                    debit=0, credit=amount,
                    description=recipe.description or _("Recette #%(id)s") % {'id': recipe.id},
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

        account_code = cls.treasury_account_code(payment.payment_method)

        with transaction.atomic():
            entry = cls._create_entry(
                'CA',
                date=timezone.now().date(),
                description=_("Paiement crédit – Vente #%(id)s") % {'id': payment.credit_sale.sale_id},
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=amount, credit=0,
                    description=_("Encaissement crédit – Vente #%(id)s") % {'id': payment.credit_sale.sale_id},
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('411'),
                    debit=0, credit=amount,
                    description=_("Règlement client – Vente #%(id)s") % {'id': payment.credit_sale.sale_id},
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
            entry = cls._create_entry(
                'CA',
                date=timezone.now().date(),
                description=_("Paiement fournisseur – %(supplier)s") % {'supplier': supplier_payment.supplier.name},
                journal='CA',
                exercise=exercise,
                daily=daily,
            )
            JournalEntryLine.objects.bulk_create([
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account('401'),
                    debit=amount, credit=0,
                    description=_("Règlement fournisseur – %(supplier)s") % {'supplier': supplier_payment.supplier.name},
                ),
                JournalEntryLine(
                    entry=entry,
                    account=cls.get_account(account_code),
                    debit=0, 
                    credit=amount,
                    description=_("Sortie trésorerie – paiement %(supplier)s") % {'supplier': supplier_payment.supplier.name},
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
                'entry__delete_at__isnull': True,
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
                    'reference': _("Vente #%(id)s") % {'id': cs.sale_id},
                    'tiers': client_name or _('Client anonyme'),
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
                    for label, _low, _high in tranches
                ],
                'totals': totals,
                'grand_total': grand_total,
                'balance_type': 'client',
                'title': _('Créances clients'),
            }
            return {
                'items': result,
                'totals': totals,
                'grand_total': grand_total,
                'tranches': [t[0] for t in tranches],
                'balance_type': 'client',
                'title': _('Créances clients'),
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
                    for label, _low, _high in tranches
                ],
                'totals': totals,
                'grand_total': grand_total,
                'balance_type': 'client',
                'title': _('Créances clients'),
}
            return {
                'items': result,
                'totals': totals,
                'grand_total': grand_total,
                'tranches': [t[0] for t in tranches],
                'balance_type': 'supplier',
                'title': _('Dettes fournisseurs'),
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
        with transaction.atomic():
            stmt = BankStatement.objects.select_for_update().get(
                id=statement_id, delete_at__isnull=True,
            )
            if stmt.is_reconciled:
                raise ValueError(_("Cette ligne de relevé est déjà rapprochée."))
            # La ligne d'écriture doit être active, du MÊME compte que le relevé,
            # et pas déjà rapprochée avec un autre relevé.
            entry_line = JournalEntryLine.objects.filter(
                id=entry_line_id,
                account=stmt.account,
                delete_at__isnull=True,
                entry__delete_at__isnull=True,
                entry__is_validated=True,
            ).first()
            if entry_line is None:
                raise ValueError(_("Ligne d'écriture introuvable ou non rapprochable avec ce compte."))
            if BankStatement.objects.filter(
                reconciled_entry=entry_line, is_reconciled=True, delete_at__isnull=True,
            ).exclude(pk=stmt.pk).exists():
                raise ValueError(_("Cette ligne d'écriture est déjà rapprochée avec un autre relevé."))

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
        from core.models.accounting_models import ExerciseClosing, Daily

        zero = Decimal('0')

        with transaction.atomic():
            # Verrouiller l'exercice : deux clôtures simultanées sont impossibles
            from core.models.accounting_models import Exercise
            exercise = Exercise.objects.select_for_update().get(pk=exercise.pk)
            if not exercise.is_active():
                raise ValueError(_("Cet exercice est déjà clôturé."))
            if ExerciseClosing.objects.filter(exercise=exercise, delete_at__isnull=True).exists():
                raise ValueError(_("Cet exercice a déjà fait l'objet d'une clôture."))
            if Daily.objects.filter(
                exercise=exercise, end_date__isnull=True, delete_at__isnull=True,
            ).exists():
                raise ValueError(_(
                    "Une journée est encore ouverte sur cet exercice. "
                    "Clôturez la journée avant de clôturer l'exercice."
                ))
            # Les à-nouveaux (AN) ne sont que le report d'ouverture : un
            # exercice qui n'a rien d'autre n'a pas d'activité à clôturer.
            if not JournalEntry.objects.filter(
                exercise=exercise, delete_at__isnull=True,
            ).exclude(journal='AN').exists():
                raise ValueError(_("Cet exercice ne contient aucune opération : rien à clôturer."))

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
            closing_entry = cls._create_entry(
                'CL',
                date=timezone.now().date(),
                description=_("Clôture exercice %(exercise)s — Résultat: %(result)s FCFA") % {'exercise': exercise, 'result': resultat},
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
                    description=_("Clôture %(code)s — %(name)s") % {
                        'code': line['account'].code, 'name': line['account'].name,
                    },
                ))

            # Ligne résultat vers compte 12
            compte_12 = cls.get_account('12')
            if resultat >= 0:
                # Bénéfice → Crédit 12
                entry_lines.append(JournalEntryLine(
                    entry=closing_entry,
                    account=compte_12,
                    debit=zero, credit=resultat,
                    description=_("Résultat de l'exercice (bénéfice)"),
                ))
            else:
                # Perte → Débit 12
                entry_lines.append(JournalEntryLine(
                    entry=closing_entry,
                    account=compte_12,
                    debit=abs(resultat), credit=zero,
                    description=_("Résultat de l'exercice (perte)"),
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
        from core.models.accounting_models import Exercise, ExerciseClosing

        old_exercise = closing.exercise
        zero = Decimal('0')

        with transaction.atomic():
            # Idempotence : une clôture ne peut ouvrir qu'UN nouvel exercice
            # (sinon les à-nouveaux seraient dupliqués à chaque appel).
            closing = ExerciseClosing.objects.select_for_update().get(pk=closing.pk)
            if closing.new_exercise_id:
                raise ValueError(_("Un nouvel exercice a déjà été ouvert pour cette clôture."))

            # Créer le nouvel exercice
            new_exercise = Exercise.objects.create(
                start_date=timezone.now(),
                end_date=None,
            )

            # Écriture d'ouverture (report à nouveau)
            opening_entry = cls._create_entry(
                'AN',
                date=timezone.now().date(),
                description=_("Report à nouveau — ouverture exercice %(exercise)s") % {'exercise': new_exercise},
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
                            description=_("Report à nouveau %(code)s") % {'code': acc.code},
                        ))
                    else:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=zero, credit=abs(balance),
                            description=_("Report à nouveau %(code)s") % {'code': acc.code},
                        ))
                else:
                    # PASSIF/PRODUIT — solde normalement créditeur
                    if balance > 0:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=zero, credit=balance,
                            description=_("Report à nouveau %(code)s") % {'code': acc.code},
                        ))
                    else:
                        entry_lines.append(JournalEntryLine(
                            entry=opening_entry,
                            account=acc,
                            debit=abs(balance), credit=zero,
                            description=_("Report à nouveau %(code)s") % {'code': acc.code},
                        ))

            # Reporter le résultat (12) vers report à nouveau (131 ou 139)
            resultat = closing.result_amount
            if resultat > 0:
                # Bénéfice → vider 12 (débit) → 131 (crédit)
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('12'),
                    debit=resultat, credit=zero,
                    description=_("Affectation résultat bénéficiaire"),
                ))
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('131'),
                    debit=zero, credit=resultat,
                    description=_("Report à nouveau — bénéfice"),
                ))
            elif resultat < 0:
                # Perte → vider 12 (crédit) → 139 (débit)
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('12'),
                    debit=zero, credit=abs(resultat),
                    description=_("Affectation résultat déficitaire"),
                ))
                entry_lines.append(JournalEntryLine(
                    entry=opening_entry,
                    account=cls.get_account('139'),
                    debit=abs(resultat), credit=zero,
                    description=_("Report à nouveau — perte"),
                ))

            if entry_lines:
                JournalEntryLine.objects.bulk_create(entry_lines)

            # Mettre à jour le closing
            closing.opening_entry = opening_entry
            closing.new_exercise = new_exercise
            closing.save()

        return new_exercise
