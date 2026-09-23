"""
Accounting-related models: Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense,
Account, JournalEntry, JournalEntryLine, Payment, SupplierPayment, Invoice.
"""

from django.db import models
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy
from django.conf import settings

from core.models.base_models import SoftDeleteModel


# ──────────────────────────────────────────────────────────────────────────────
# Plan Comptable (OHADA / SYSCOHADA)
# ──────────────────────────────────────────────────────────────────────────────

class Account(SoftDeleteModel):
    """
    Compte du plan comptable OHADA/SYSCOHADA.
    Classes : 1-Capitaux, 2-Immobilisations, 3-Stocks, 4-Tiers,
              5-Trésorerie, 6-Charges, 7-Produits.
    """
    # Contexte de traduction : « Actif »/« Produit » désignent ici des types de comptes
    # (Assets / Revenue), pas l'état actif d'une fiche ni un article du catalogue.
    ACCOUNT_TYPE_CHOICES = [
        ('ACTIF', pgettext_lazy('type de compte', 'Actif')),
        ('PASSIF', pgettext_lazy('type de compte', 'Passif')),
        ('CHARGE', pgettext_lazy('type de compte', 'Charge')),
        ('PRODUIT', pgettext_lazy('type de compte', 'Produit')),
    ]

    code = models.CharField(max_length=20, unique=True, verbose_name=_("Code du compte"))
    name = models.CharField(max_length=255, verbose_name=_("Libellé du compte"))
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES, verbose_name=_("Type de compte"))
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='children', verbose_name=_("Compte parent")
    )
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"))
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))

    class Meta:
        db_table = 'account'
        verbose_name = _('Compte comptable')
        verbose_name_plural = _('Comptes comptables')
        ordering = ['code']

    def __str__(self):
        # Les noms des comptes semés (DEFAULT_ACCOUNTS) sont marqués gettext_noop : traduits à l'affichage
        return f"{self.code} - {gettext(self.name)}"

    def get_balance(self, exercise=None):
        """
        Calcule le solde du compte.
        Pour ACTIF/CHARGE : solde = total débits − total crédits
        Pour PASSIF/PRODUIT : solde = total crédits − total débits
        """
        from django.db.models import Sum

        # Ignorer les lignes et écritures soft-supprimées, sinon le solde
        # diverge des totaux de la balance.
        filters = {
            'entry__is_validated': True,
            'entry__delete_at__isnull': True,
            'delete_at__isnull': True,
            'account': self,
        }
        if exercise:
            filters['entry__exercise'] = exercise

        totals = JournalEntryLine.objects.filter(**filters).aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        total_debit = totals['total_debit'] or 0
        total_credit = totals['total_credit'] or 0

        if self.account_type in ('ACTIF', 'CHARGE'):
            return total_debit - total_credit
        else:
            return total_credit - total_debit


class JournalEntry(SoftDeleteModel):
    """
    Écriture comptable (pièce comptable).
    Chaque écriture contient au minimum 2 lignes (partie double).
    """
    JOURNAL_CHOICES = [
        ('VE', _('Journal des Ventes')),
        ('AC', _('Journal des Achats')),
        ('CA', _('Journal de Caisse')),
        ('BQ', _('Journal de Banque')),
        ('OD', _('Journal des Opérations Diverses')),
        ('AN', _('À-nouveaux (ouverture)')),
        ('CL', _('Clôture')),
    ]

    reference = models.CharField(max_length=50, unique=True, verbose_name=_("Référence"))
    date = models.DateField(verbose_name=_("Date de l'écriture"))
    description = models.CharField(max_length=500, verbose_name=_("Libellé"))
    journal = models.CharField(max_length=2, choices=JOURNAL_CHOICES, default='OD', verbose_name=_("Journal"))
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='journal_entries', verbose_name=_("Exercice"))
    daily = models.ForeignKey('Daily', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name=_("Journée"))
    is_validated = models.BooleanField(default=True, verbose_name=_("Validée"))

    # Liens optionnels vers l'opération source
    sale = models.ForeignKey('Sale', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name=_("Vente liée"))
    supply = models.ForeignKey('Supply', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name=_("Approvisionnement lié"))
    expense = models.ForeignKey('DailyExpense', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name=_("Dépense liée"))

    class Meta:
        db_table = 'journal_entry'
        verbose_name = _('Écriture comptable')
        verbose_name_plural = _('Écritures comptables')
        ordering = ['-date', '-create_at']

    def __str__(self):
        return f"{self.reference} - {self.description}"

    def is_balanced(self):
        """Vérifie que l'écriture est équilibrée (débits = crédits)."""
        from django.db.models import Sum
        totals = self.lines.filter(delete_at__isnull=True).aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        total_debit = totals['total_debit'] or 0
        total_credit = totals['total_credit'] or 0
        return abs(total_debit - total_credit) < 0.01

    def get_total(self):
        """Retourne le total de l'écriture (somme des débits)."""
        from django.db.models import Sum
        return self.lines.aggregate(total=Sum('debit'))['total'] or 0


class JournalEntryLine(SoftDeleteModel):
    """
    Ligne d'écriture comptable (débit OU crédit sur un compte).
    """
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines', verbose_name=_("Écriture"))
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='entry_lines', verbose_name=_("Compte"))
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name=_("Débit"))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name=_("Crédit"))
    description = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Libellé ligne"))

    class Meta:
        db_table = 'journal_entry_line'
        verbose_name = _("Ligne d'écriture")
        verbose_name_plural = _("Lignes d'écriture")
        ordering = ['id']

    def __str__(self):
        if self.debit > 0:
            return gettext("%(code)s — Débit %(debit)s") % {'code': self.account.code, 'debit': self.debit}
        return gettext("%(code)s — Crédit %(credit)s") % {'code': self.account.code, 'credit': self.credit}


# ──────────────────────────────────────────────────────────────────────────────
# Modèles existants
# ──────────────────────────────────────────────────────────────────────────────

class Exercise(SoftDeleteModel):
    """
    Fiscal exercise/year model.
    """
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'exercise'
        # managed = False
        verbose_name = _('Exercice')
        verbose_name_plural = _('Exercices')
        ordering = ['-start_date']
    
    def __str__(self):
        return gettext("Exercice %(label)s") % {'label': self.start_date.year if self.start_date else self.id}
    
    def is_active(self):
        """Check if the exercise is currently active."""
        return self.end_date is None


class Daily(SoftDeleteModel):
    """
    Daily session model for tracking daily operations.
    """
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='dailies')
    
    class Meta:
        db_table = 'daily'
        # managed = False
        verbose_name = _('Journée')
        verbose_name_plural = _('Journées')
        ordering = ['-start_date']
    
    def __str__(self):
        return gettext("Journée %(label)s") % {'label': self.start_date.strftime('%Y-%m-%d') if self.start_date else self.id}
    
    def is_open(self):
        """Check if the daily session is still open."""
        return self.end_date is None


class ExpenseType(SoftDeleteModel):
    """
    Type of expense model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'expense_type'
        # managed = False
        verbose_name = _('Type de dépense')
        verbose_name_plural = _('Types de dépenses')
    
    def __str__(self):
        return self.name


class RecipeType(SoftDeleteModel):
    """
    Type of recipe/income model.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'recipe_type'
        # managed = False
        verbose_name = _('Type de recette')
        verbose_name_plural = _('Types de recettes')
    
    def __str__(self):
        return self.name


class DailyExpense(SoftDeleteModel):
    """
    Daily expense model.
    """
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    daily = models.ForeignKey(Daily, on_delete=models.CASCADE, related_name='expenses')
    expense_type = models.ForeignKey(ExpenseType, on_delete=models.SET_NULL, null=True, related_name='daily_expenses')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='expenses')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='expenses')
    account = models.ForeignKey(
        'Account', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses', verbose_name=_("Compte comptable")
    )
    accounting_pending = models.BooleanField(
        default=False,
        verbose_name=_("Écriture comptable en attente"),
        help_text=_(
            "Vrai si l'écriture comptable de la dépense a échoué et doit être "
            "rejouée (commande replay_accounting)."
        ),
    )

    class Meta:
        db_table = 'daily_expense'
        # managed = False
        verbose_name = _('Dépense quotidienne')
        verbose_name_plural = _('Dépenses quotidiennes')
        ordering = ['-create_at']
    
    def __str__(self):
        return gettext("Dépense %(amount)s - %(expense_type)s") % {'amount': self.amount, 'expense_type': self.expense_type}


class DailyRecipe(SoftDeleteModel):
    """
    Daily recipe/income model.
    """
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    daily = models.ForeignKey(Daily, on_delete=models.CASCADE, related_name='recipes')
    recipe_type = models.ForeignKey(RecipeType, on_delete=models.SET_NULL, null=True, related_name='daily_recipes')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='recipes')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='recipes')
    account = models.ForeignKey(
        'Account', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recipes', verbose_name=_("Compte comptable")
    )
    accounting_pending = models.BooleanField(
        default=False,
        verbose_name=_("Écriture comptable en attente"),
        help_text=_(
            "Vrai si l'écriture comptable de la recette a échoué et doit être "
            "rejouée (commande replay_accounting)."
        ),
    )

    class Meta:
        db_table = 'daily_recipe'
        # managed = False
        verbose_name = _('Recette quotidienne')
        verbose_name_plural = _('Recettes quotidiennes')
        ordering = ['-create_at']
    
    def __str__(self):
        return gettext("Recette %(amount)s - %(recipe_type)s") % {'amount': self.amount, 'recipe_type': self.recipe_type}


class ProductExpense(SoftDeleteModel):
    """
    Product expense model for tracking product-related expenses.
    """
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='expenses')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'product_expense'
        # managed = False
        verbose_name = _('Dépense produit')
        verbose_name_plural = _('Dépenses produits')

    def __str__(self):
        return gettext("Dépense %(amount)s pour %(product)s") % {'amount': self.amount, 'product': self.product.name}


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Modes de paiement, Paiements, Factures
# ──────────────────────────────────────────────────────────────────────────────

PAYMENT_METHOD_CHOICES = [
    ('CASH', _('Espèces')),
    ('MOBILE_MONEY', _('Mobile Money')),
    ('BANK_TRANSFER', _('Virement bancaire')),
    ('CHECK', _('Chèque')),
]

# Mapping mode de paiement → code compte comptable de trésorerie
PAYMENT_METHOD_ACCOUNT_MAP = {
    'CASH': '571',          # Caisse principale
    'MOBILE_MONEY': '585',  # Mobile Money
    'BANK_TRANSFER': '521', # Banque locale
    'CHECK': '521',         # Banque locale (chèque)
}


class Payment(SoftDeleteModel):
    """
    Paiement reçu sur une vente à crédit.
    Chaque paiement génère une écriture comptable :
    Débit  571/521/585 (Trésorerie) | montant
    Crédit 411         (Clients)    | montant
    """
    credit_sale = models.ForeignKey(
        'CreditSale', on_delete=models.CASCADE,
        related_name='payments', verbose_name=_("Vente à crédit")
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Montant"))
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES,
        default='CASH', verbose_name=_("Mode de paiement")
    )
    payment_date = models.DateField(verbose_name=_("Date de paiement"))
    reference = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name=_("Référence (n° chèque, ID transaction...)")
    )
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recorded_payments',
        verbose_name=_("Enregistré par")
    )
    daily = models.ForeignKey(
        'Daily', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name=_("Journée")
    )

    class Meta:
        db_table = 'payment'
        verbose_name = _('Paiement client')
        verbose_name_plural = _('Paiements clients')
        ordering = ['-payment_date', '-create_at']

    def __str__(self):
        return gettext("Paiement %(amount)s FCFA – Vente #%(sale_id)s") % {'amount': self.amount, 'sale_id': self.credit_sale.sale_id}


class SupplierPayment(SoftDeleteModel):
    """
    Paiement effectué à un fournisseur.
    Débit  401 Fournisseurs  | montant
    Crédit 571/521/585       | montant
    """
    supplier = models.ForeignKey(
        'Supplier', on_delete=models.CASCADE,
        related_name='payments', verbose_name=_("Fournisseur")
    )
    supply = models.ForeignKey(
        'Supply', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name=_("Approvisionnement lié")
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Montant"))
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES,
        default='CASH', verbose_name=_("Mode de paiement")
    )
    payment_date = models.DateField(verbose_name=_("Date de paiement"))
    reference = models.CharField(
        max_length=100, null=True, blank=True, verbose_name=_("Référence")
    )
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='supplier_payments',
        verbose_name=_("Enregistré par")
    )
    daily = models.ForeignKey(
        'Daily', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_payments', verbose_name=_("Journée")
    )
    accounting_pending = models.BooleanField(
        default=False,
        verbose_name=_("Écriture comptable en attente"),
        help_text=_(
            "Vrai si l'écriture comptable du paiement a échoué et doit être "
            "rejouée (commande replay_accounting)."
        ),
    )

    class Meta:
        db_table = 'supplier_payment'
        verbose_name = _('Paiement fournisseur')
        verbose_name_plural = _('Paiements fournisseurs')
        ordering = ['-payment_date', '-create_at']

    def __str__(self):
        return gettext("Paiement %(amount)s FCFA – %(supplier)s") % {'amount': self.amount, 'supplier': self.supplier.name}


class Invoice(SoftDeleteModel):
    """
    Facture de vente formelle.
    """
    INVOICE_STATUS_CHOICES = [
        ('DRAFT', _('Brouillon')),
        ('SENT', _('Envoyée')),
        ('PAID', _('Payée')),
        ('CANCELLED', _('Annulée')),
    ]

    sale = models.OneToOneField(
        'Sale', on_delete=models.CASCADE,
        related_name='invoice', verbose_name=_("Vente")
    )
    invoice_number = models.CharField(
        max_length=50, unique=True, verbose_name=_("N° Facture")
    )
    invoice_date = models.DateField(verbose_name=_("Date de facture"))
    due_date = models.DateField(
        null=True, blank=True, verbose_name=_("Date d'échéance")
    )
    status = models.CharField(
        max_length=10, choices=INVOICE_STATUS_CHOICES,
        default='DRAFT', verbose_name=_("Statut")
    )
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))

    class Meta:
        db_table = 'invoice'
        verbose_name = _('Facture')
        verbose_name_plural = _('Factures')
        ordering = ['-invoice_date', '-create_at']

    def __str__(self):
        return gettext("Facture %(number)s") % {'number': self.invoice_number}

    @staticmethod
    def generate_invoice_number():
        """Génère un numéro de facture unique : FAC-YYYYMMDD-001"""
        from datetime import date as date_cls
        today = date_cls.today().strftime('%Y%m%d')
        prefix = f"FAC-{today}"
        last = Invoice.objects.filter(
            invoice_number__startswith=prefix
        ).order_by('-invoice_number').first()
        if last:
            seq = int(last.invoice_number.split('-')[-1]) + 1
        else:
            seq = 1
        return f"{prefix}-{seq:03d}"


# ──────────────────────────────────────────────────────────────────────────────
# Phase 4 — TVA, Rapprochement bancaire, Clôture d'exercice
# ──────────────────────────────────────────────────────────────────────────────

class TaxRate(SoftDeleteModel):
    """
    Taux de TVA configurables.
    Au Cameroun : TVA standard = 19.25% (19% + 1.25% CAC).
    """
    name = models.CharField(max_length=100, verbose_name=_("Nom du taux"))
    rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name=_("Taux (%)"),
        help_text=_("Ex: 19.25 pour 19.25%")
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Taux par défaut"))
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"))

    class Meta:
        db_table = 'tax_rate'
        verbose_name = _('Taux de TVA')
        verbose_name_plural = _('Taux de TVA')
        ordering = ['rate']

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class BankStatement(SoftDeleteModel):
    """
    Relevé bancaire importé pour rapprochement.
    Chaque ligne représente une transaction sur le relevé bancaire.
    """
    STATEMENT_TYPE_CHOICES = [
        ('CREDIT', _('Crédit (entrée)')),
        ('DEBIT', _('Débit (sortie)')),
    ]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE,
        related_name='bank_statements',
        verbose_name=_("Compte bancaire"),
        help_text=_("Compte 521 (Banque) ou 585 (Mobile Money)")
    )
    statement_date = models.DateField(verbose_name=_("Date de l'opération"))
    description = models.CharField(max_length=500, verbose_name=_("Libellé"))
    reference = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name=_("Référence bancaire")
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Montant"))
    statement_type = models.CharField(
        max_length=6, choices=STATEMENT_TYPE_CHOICES,
        verbose_name=_("Type d'opération")
    )
    is_reconciled = models.BooleanField(default=False, verbose_name=_("Rapproché"))
    reconciled_entry = models.ForeignKey(
        JournalEntryLine, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reconciled_statements',
        verbose_name=_("Ligne d'écriture rapprochée")
    )
    reconciled_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date de rapprochement"))
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reconciled_statements',
        verbose_name=_("Rapproché par")
    )

    class Meta:
        db_table = 'bank_statement'
        verbose_name = _('Relevé bancaire')
        verbose_name_plural = _('Relevés bancaires')
        ordering = ['-statement_date', '-create_at']

    def __str__(self):
        return f"{self.statement_date} — {self.description} — {self.amount} FCFA"


class ExerciseClosing(SoftDeleteModel):
    """
    Historique de clôture d'exercice.
    Enregistre les détails de chaque clôture pour audit.
    """
    exercise = models.OneToOneField(
        Exercise, on_delete=models.CASCADE,
        related_name='closing',
        verbose_name=_("Exercice clôturé")
    )
    closed_at = models.DateTimeField(verbose_name=_("Date de clôture"))
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='closed_exercises',
        verbose_name=_("Clôturé par")
    )
    result_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        verbose_name=_("Résultat de l'exercice (bénéfice/perte)")
    )
    closing_entry = models.ForeignKey(
        JournalEntry, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercise_closing',
        verbose_name=_("Écriture de clôture")
    )
    opening_entry = models.ForeignKey(
        JournalEntry, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercise_opening',
        verbose_name=_("Écriture d'ouverture (report à nouveau)")
    )
    new_exercise = models.ForeignKey(
        Exercise, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='opened_from_closing',
        verbose_name=_("Nouvel exercice créé")
    )
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))

    class Meta:
        db_table = 'exercise_closing'
        verbose_name = _("Clôture d'exercice")
        verbose_name_plural = _("Clôtures d'exercice")
        ordering = ['-closed_at']

    def __str__(self):
        return gettext("Clôture %(exercise)s — Résultat: %(result)s FCFA") % {'exercise': self.exercise, 'result': self.result_amount}

