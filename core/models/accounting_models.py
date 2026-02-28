"""
Accounting-related models: Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense,
Account, JournalEntry, JournalEntryLine, Payment, SupplierPayment, Invoice.
"""

from django.db import models
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
    ACCOUNT_TYPE_CHOICES = [
        ('ACTIF', 'Actif'),
        ('PASSIF', 'Passif'),
        ('CHARGE', 'Charge'),
        ('PRODUIT', 'Produit'),
    ]

    code = models.CharField(max_length=20, unique=True, verbose_name="Code du compte")
    name = models.CharField(max_length=255, verbose_name="Libellé du compte")
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES, verbose_name="Type de compte")
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='children', verbose_name="Compte parent"
    )
    description = models.TextField(null=True, blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        db_table = 'account'
        verbose_name = 'Compte comptable'
        verbose_name_plural = 'Comptes comptables'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def get_balance(self, exercise=None):
        """
        Calcule le solde du compte.
        Pour ACTIF/CHARGE : solde = total débits − total crédits
        Pour PASSIF/PRODUIT : solde = total crédits − total débits
        """
        from django.db.models import Sum

        filters = {'entry__is_validated': True, 'account': self}
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
        ('VE', 'Journal des Ventes'),
        ('AC', 'Journal des Achats'),
        ('CA', 'Journal de Caisse'),
        ('BQ', 'Journal de Banque'),
        ('OD', 'Journal des Opérations Diverses'),
    ]

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    date = models.DateField(verbose_name="Date de l'écriture")
    description = models.CharField(max_length=500, verbose_name="Libellé")
    journal = models.CharField(max_length=2, choices=JOURNAL_CHOICES, default='OD', verbose_name="Journal")
    exercise = models.ForeignKey('Exercise', on_delete=models.CASCADE, related_name='journal_entries', verbose_name="Exercice")
    daily = models.ForeignKey('Daily', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name="Journée")
    is_validated = models.BooleanField(default=True, verbose_name="Validée")

    # Liens optionnels vers l'opération source
    sale = models.ForeignKey('Sale', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name="Vente liée")
    supply = models.ForeignKey('Supply', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name="Approvisionnement lié")
    expense = models.ForeignKey('DailyExpense', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries', verbose_name="Dépense liée")

    class Meta:
        db_table = 'journal_entry'
        verbose_name = 'Écriture comptable'
        verbose_name_plural = 'Écritures comptables'
        ordering = ['-date', '-create_at']

    def __str__(self):
        return f"{self.reference} - {self.description}"

    def is_balanced(self):
        """Vérifie que l'écriture est équilibrée (débits = crédits)."""
        from django.db.models import Sum
        totals = self.lines.aggregate(
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
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines', verbose_name="Écriture")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='entry_lines', verbose_name="Compte")
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Débit")
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Crédit")
    description = models.CharField(max_length=255, null=True, blank=True, verbose_name="Libellé ligne")

    class Meta:
        db_table = 'journal_entry_line'
        verbose_name = "Ligne d'écriture"
        verbose_name_plural = "Lignes d'écriture"
        ordering = ['id']

    def __str__(self):
        if self.debit > 0:
            return f"{self.account.code} — Débit {self.debit}"
        return f"{self.account.code} — Crédit {self.credit}"


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
        verbose_name = 'Exercice'
        verbose_name_plural = 'Exercices'
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Exercice {self.start_date.year if self.start_date else self.id}"
    
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
        verbose_name = 'Journée'
        verbose_name_plural = 'Journées'
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Journée {self.start_date.strftime('%Y-%m-%d') if self.start_date else self.id}"
    
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
        verbose_name = 'Type de dépense'
        verbose_name_plural = 'Types de dépenses'
    
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
        verbose_name = 'Type de recette'
        verbose_name_plural = 'Types de recettes'
    
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
        related_name='expenses', verbose_name="Compte comptable"
    )
    
    class Meta:
        db_table = 'daily_expense'
        # managed = False
        verbose_name = 'Dépense quotidienne'
        verbose_name_plural = 'Dépenses quotidiennes'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Dépense {self.amount} - {self.expense_type}"


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
        related_name='recipes', verbose_name="Compte comptable"
    )
    
    class Meta:
        db_table = 'daily_recipe'
        # managed = False
        verbose_name = 'Recette quotidienne'
        verbose_name_plural = 'Recettes quotidiennes'
        ordering = ['-create_at']
    
    def __str__(self):
        return f"Recette {self.amount} - {self.recipe_type}"


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
        verbose_name = 'Dépense produit'
        verbose_name_plural = 'Dépenses produits'

    def __str__(self):
        return f"Dépense {self.amount} pour {self.product.name}"


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Modes de paiement, Paiements, Factures
# ──────────────────────────────────────────────────────────────────────────────

PAYMENT_METHOD_CHOICES = [
    ('CASH', 'Espèces'),
    ('MOBILE_MONEY', 'Mobile Money'),
    ('BANK_TRANSFER', 'Virement bancaire'),
    ('CHECK', 'Chèque'),
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
        related_name='payments', verbose_name="Vente à crédit"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant")
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES,
        default='CASH', verbose_name="Mode de paiement"
    )
    payment_date = models.DateField(verbose_name="Date de paiement")
    reference = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Référence (n° chèque, ID transaction...)"
    )
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recorded_payments',
        verbose_name="Enregistré par"
    )
    daily = models.ForeignKey(
        'Daily', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name="Journée"
    )

    class Meta:
        db_table = 'payment'
        verbose_name = 'Paiement client'
        verbose_name_plural = 'Paiements clients'
        ordering = ['-payment_date', '-create_at']

    def __str__(self):
        return f"Paiement {self.amount} FCFA – Vente #{self.credit_sale.sale_id}"


class SupplierPayment(SoftDeleteModel):
    """
    Paiement effectué à un fournisseur.
    Débit  401 Fournisseurs  | montant
    Crédit 571/521/585       | montant
    """
    supplier = models.ForeignKey(
        'Supplier', on_delete=models.CASCADE,
        related_name='payments', verbose_name="Fournisseur"
    )
    supply = models.ForeignKey(
        'Supply', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name="Approvisionnement lié"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant")
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES,
        default='CASH', verbose_name="Mode de paiement"
    )
    payment_date = models.DateField(verbose_name="Date de paiement")
    reference = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="Référence"
    )
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='supplier_payments',
        verbose_name="Enregistré par"
    )
    daily = models.ForeignKey(
        'Daily', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_payments', verbose_name="Journée"
    )

    class Meta:
        db_table = 'supplier_payment'
        verbose_name = 'Paiement fournisseur'
        verbose_name_plural = 'Paiements fournisseurs'
        ordering = ['-payment_date', '-create_at']

    def __str__(self):
        return f"Paiement {self.amount} FCFA – {self.supplier.name}"


class Invoice(SoftDeleteModel):
    """
    Facture de vente formelle.
    """
    INVOICE_STATUS_CHOICES = [
        ('DRAFT', 'Brouillon'),
        ('SENT', 'Envoyée'),
        ('PAID', 'Payée'),
        ('CANCELLED', 'Annulée'),
    ]

    sale = models.OneToOneField(
        'Sale', on_delete=models.CASCADE,
        related_name='invoice', verbose_name="Vente"
    )
    invoice_number = models.CharField(
        max_length=50, unique=True, verbose_name="N° Facture"
    )
    invoice_date = models.DateField(verbose_name="Date de facture")
    due_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'échéance"
    )
    status = models.CharField(
        max_length=10, choices=INVOICE_STATUS_CHOICES,
        default='DRAFT', verbose_name="Statut"
    )
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")

    class Meta:
        db_table = 'invoice'
        verbose_name = 'Facture'
        verbose_name_plural = 'Factures'
        ordering = ['-invoice_date', '-create_at']

    def __str__(self):
        return f"Facture {self.invoice_number}"

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
    name = models.CharField(max_length=100, verbose_name="Nom du taux")
    rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name="Taux (%)",
        help_text="Ex: 19.25 pour 19.25%"
    )
    is_default = models.BooleanField(default=False, verbose_name="Taux par défaut")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    description = models.TextField(null=True, blank=True, verbose_name="Description")

    class Meta:
        db_table = 'tax_rate'
        verbose_name = 'Taux de TVA'
        verbose_name_plural = 'Taux de TVA'
        ordering = ['rate']

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class BankStatement(SoftDeleteModel):
    """
    Relevé bancaire importé pour rapprochement.
    Chaque ligne représente une transaction sur le relevé bancaire.
    """
    STATEMENT_TYPE_CHOICES = [
        ('CREDIT', 'Crédit (entrée)'),
        ('DEBIT', 'Débit (sortie)'),
    ]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE,
        related_name='bank_statements',
        verbose_name="Compte bancaire",
        help_text="Compte 521 (Banque) ou 585 (Mobile Money)"
    )
    statement_date = models.DateField(verbose_name="Date de l'opération")
    description = models.CharField(max_length=500, verbose_name="Libellé")
    reference = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Référence bancaire"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant")
    statement_type = models.CharField(
        max_length=6, choices=STATEMENT_TYPE_CHOICES,
        verbose_name="Type d'opération"
    )
    is_reconciled = models.BooleanField(default=False, verbose_name="Rapproché")
    reconciled_entry = models.ForeignKey(
        JournalEntryLine, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reconciled_statements',
        verbose_name="Ligne d'écriture rapprochée"
    )
    reconciled_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de rapprochement")
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reconciled_statements',
        verbose_name="Rapproché par"
    )

    class Meta:
        db_table = 'bank_statement'
        verbose_name = 'Relevé bancaire'
        verbose_name_plural = 'Relevés bancaires'
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
        verbose_name="Exercice clôturé"
    )
    closed_at = models.DateTimeField(verbose_name="Date de clôture")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='closed_exercises',
        verbose_name="Clôturé par"
    )
    result_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        verbose_name="Résultat de l'exercice (bénéfice/perte)"
    )
    closing_entry = models.ForeignKey(
        JournalEntry, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercise_closing',
        verbose_name="Écriture de clôture"
    )
    opening_entry = models.ForeignKey(
        JournalEntry, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercise_opening',
        verbose_name="Écriture d'ouverture (report à nouveau)"
    )
    new_exercise = models.ForeignKey(
        Exercise, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='opened_from_closing',
        verbose_name="Nouvel exercice créé"
    )
    notes = models.TextField(null=True, blank=True, verbose_name="Notes")

    class Meta:
        db_table = 'exercise_closing'
        verbose_name = "Clôture d'exercice"
        verbose_name_plural = "Clôtures d'exercice"
        ordering = ['-closed_at']

    def __str__(self):
        return f"Clôture {self.exercise} — Résultat: {self.result_amount} FCFA"

