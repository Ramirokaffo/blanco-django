"""
Django admin configuration for core models.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import (
    # User models
    CustomUser, Client, Supplier,
    # Product models
    Category, Gamme, Rayon, GrammageType, Product, ProductImage,
    # Sale models
    Sale, SaleProduct, CreditSale, Refund,
    # Inventory models
    Supply, Inventory, InventorySnapshot, DailyInventory,
    # Accounting models
    Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense,
    # Comptabilité (nouveaux modèles)
    Account, JournalEntry, JournalEntryLine,
    # Phase 2 — Paiements & Factures
    Payment, SupplierPayment, Invoice,
    # Phase 4 — TVA, Rapprochement, Clôture
    TaxRate, BankStatement, ExerciseClosing,
    # Settings models
    SystemSettings, AppModule,
)
from core.services.staff_service import StaffService


def configure_admin_site():
    """Configure le site d'administration BLANCO"""
    admin.site.site_header = _("Administration BLANCO")
    admin.site.site_title = _("Administration BLANCO")
    admin.site.index_title = _("Panneau d'administration BLANCO")
# Appliquer la configuration
configure_admin_site()


class FinancialRecordAdmin(admin.ModelAdmin):
    """
    Base pour les pièces financières (ventes, achats, paiements, écritures) :
    - pas de suppression physique (l'annulation métier passe par les services,
      qui restaurent le stock et contrepassent l'écriture) ;
    - les montants sont en lecture seule.
    """
    protected_fields = ()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        base = tuple(super().get_readonly_fields(request, obj))
        if obj is None:
            return base
        return tuple(dict.fromkeys(base + tuple(self.protected_fields)))

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


# Le token DRF ne doit pas être lisible en clair dans l'admin
try:
    from rest_framework.authtoken.models import TokenProxy
    admin.site.unregister(TokenProxy)
except Exception:  # pragma: no cover - déjà désenregistré ou modèle absent
    pass

# User Models Admin
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Admin pour le modèle CustomUser (Staff)"""
    list_display = ('username', 'email', 'firstname', 'lastname', 'role', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'role', 'gender')
    search_fields = ('username', 'firstname', 'lastname', 'email', 'phone_number')
    ordering = ('-date_joined',)

    # Ajouter les champs personnalisés aux fieldsets
    fieldsets = UserAdmin.fieldsets + (
        (_('Informations supplémentaires'), {
            'fields': ('firstname', 'lastname', 'phone_number', 'role', 'gender', 'profil', 'delete_at')
        }),
        (_('Modules autorisés'), {
            'fields': ('allowed_modules',),
            'description': _('Sélectionnez les modules auxquels cet utilisateur a accès. Les superusers ont accès à tout.')
        }),
    )

    # Ajouter les champs personnalisés au formulaire de création
    add_fieldsets = UserAdmin.add_fieldsets + (
        (_('Informations supplémentaires'), {
            'fields': ('firstname', 'lastname', 'phone_number', 'role', 'gender', 'profil')
        }),
    )

    filter_horizontal = ('allowed_modules', 'groups', 'user_permissions')

    def save_model(self, request, obj, form, change):
        """
        Empêche de retirer les droits du dernier administrateur.

        Sans ce contrôle, un administrateur peut se décocher « Actif » ou
        « Statut super-utilisateur » et s'enfermer dehors : plus personne ne
        peut alors gérer les comptes, et seule une intervention sur la base
        rouvre l'accès.
        """
        if change and obj.pk:
            ancien = CustomUser.objects.filter(pk=obj.pk).first()
            perd_ses_droits = ancien is not None and ancien.is_superuser and (
                not obj.is_superuser or not obj.is_active or obj.delete_at is not None
            )
            if perd_ses_droits:
                StaffService.ensure_not_last_superuser(ancien)
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        StaffService.ensure_not_last_superuser(obj)
        super().delete_model(request, obj)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('get_full_name', 'phone_number', 'email', 'gender', 'create_at')
    list_filter = ('gender', 'create_at')
    search_fields = ('firstname', 'lastname', 'phone_number', 'email')
    ordering = ('-create_at',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_phone', 'contact_email', 'niu', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('name', 'contact_phone', 'contact_email', 'niu')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


# Product Models Admin
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Gamme)
class GammeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Rayon)
class RayonAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(GrammageType)
class GrammageTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'category', 'stock', 'stock_limit', "actual_price", "last_purchase_price", 'is_price_reducible')
    list_filter = ('category', 'gamme', 'rayon', 'is_price_reducible', 'create_at')
    search_fields = ('code', 'name', 'description', 'brand')
    list_editable = ['stock_limit', 'actual_price', 'is_price_reducible', "last_purchase_price"]
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'image', 'is_primary', 'create_at')
    list_filter = ('is_primary', 'create_at')
    search_fields = ('product__name', 'image')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Sale Models Admin
@admin.register(Sale)
class SaleAdmin(FinancialRecordAdmin):
    list_display = ('id', 'total', 'client', 'staff', 'is_paid', 'is_credit', 'daily', 'create_at')
    list_filter = ('is_paid', 'is_credit', 'create_at')
    search_fields = ('client__firstname', 'client__lastname', 'staff__username')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)
    protected_fields = ('total', 'is_credit', 'daily', 'delete_at')


@admin.register(SaleProduct)
class SaleProductAdmin(FinancialRecordAdmin):
    list_display = ('sale', 'product', 'quantity', "unit_price", 'get_subtotal')
    list_filter = ('create_at',)
    search_fields = ('sale__id', 'product__name')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)
    protected_fields = ('sale', 'product', 'quantity', 'unit_price')


@admin.register(CreditSale)
class CreditSaleAdmin(FinancialRecordAdmin):
    list_display = ('sale', 'amount_paid', 'amount_remaining', 'due_date', 'is_fully_paid', 'create_at')
    list_filter = ('is_fully_paid', 'due_date', 'create_at')
    search_fields = ('sale__id',)
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)
    protected_fields = ('sale', 'amount_paid', 'amount_remaining', 'is_fully_paid')


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('sale', 'value', 'reason', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('sale__id', 'reason')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Inventory Models Admin
@admin.register(Supply)
class SupplyAdmin(FinancialRecordAdmin):
    list_display = ('product', 'supplier', 'quantity', "purchase_cost", 'selling_price', 'total_price', 'expiration_date', 'create_at')
    list_filter = ('expiration_date', 'create_at')
    search_fields = ('product__name', 'supplier__name')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)
    protected_fields = ('product', 'quantity', 'purchase_cost', 'total_price', 'is_credit', 'daily', 'delete_at')


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'valid_product_count', 'invalid_product_count', 'is_close', 'staff', 'exercise', 'create_at')
    list_filter = ('create_at', 'exercise')
    search_fields = ('product__name', 'staff__username')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(InventorySnapshot)
class InventorySnapshotAdmin(admin.ModelAdmin):
    list_display = ('product', 'exercise', 'stock_before', 'total_valid', 'total_invalid', 'total_counted', 'stock_after', 'selling_price', 'purchase_price', 'create_at')
    list_filter = ('exercise', 'create_at')
    search_fields = ('product__name', 'product__code')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(DailyInventory)
class DailyInventoryAdmin(admin.ModelAdmin):
    list_display = ('daily', 'total_sales', 'total_expenses', 'total_recipes', 'cash_in_hand', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('daily__id',)
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Accounting Models Admin
@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('id', 'start_date', 'end_date', 'is_active')
    list_filter = ('start_date', 'end_date')
    ordering = ('-start_date',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Daily)
class DailyAdmin(admin.ModelAdmin):
    list_display = ('id', 'start_date', 'end_date', 'exercise', 'is_open')
    list_filter = ('start_date', 'end_date')
    ordering = ('-start_date',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(ExpenseType)
class ExpenseTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(RecipeType)
class RecipeTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'create_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(DailyExpense)
class DailyExpenseAdmin(admin.ModelAdmin):
    list_display = ('amount', 'expense_type', 'daily', 'staff', 'exercise', 'create_at')
    list_filter = ('expense_type', 'create_at')
    search_fields = ('description', 'staff__username')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(DailyRecipe)
class DailyRecipeAdmin(admin.ModelAdmin):
    list_display = ('amount', 'recipe_type', 'daily', 'staff', 'exercise', 'create_at')
    list_filter = ('recipe_type', 'create_at')
    search_fields = ('description', 'staff__username')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(ProductExpense)
class ProductExpenseAdmin(admin.ModelAdmin):
    list_display = ('product', 'amount', 'description', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('product__name', 'description')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Comptabilité (Plan comptable & Journal)
class JournalEntryLineInline(admin.TabularInline):
    """Lignes d'écriture en consultation seule (l'équilibre débit/crédit est garanti par les services)."""
    model = JournalEntryLine
    extra = 0
    can_delete = False
    readonly_fields = ('account', 'debit', 'credit', 'description', 'create_at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('code',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(JournalEntry)
class JournalEntryAdmin(FinancialRecordAdmin):
    list_display = ('reference', 'date', 'journal', 'description', 'is_validated', 'exercise')
    list_filter = ('journal', 'is_validated', 'date')
    search_fields = ('reference', 'description')
    ordering = ('-date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)
    protected_fields = ('reference', 'journal', 'exercise', 'daily', 'sale', 'supply', 'expense', 'is_validated')
    inlines = [JournalEntryLineInline]


@admin.register(JournalEntryLine)
class JournalEntryLineAdmin(FinancialRecordAdmin):
    protected_fields = ('entry', 'account', 'debit', 'credit')
    list_display = ('entry', 'account', 'debit', 'credit', 'description')
    list_filter = ('account',)
    search_fields = ('entry__reference', 'account__code', 'description')
    ordering = ('-entry__date',)
    readonly_fields = ('create_at', 'delete_at',)


# Phase 2 — Paiements & Factures
@admin.register(Payment)
class PaymentAdmin(FinancialRecordAdmin):
    list_display = ('credit_sale', 'amount', 'payment_method', 'payment_date', 'staff', 'create_at')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('credit_sale__sale__id', 'reference')
    ordering = ('-payment_date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(FinancialRecordAdmin):
    list_display = ('supplier', 'amount', 'payment_method', 'payment_date', 'staff', 'create_at')
    list_filter = ('payment_method', 'payment_date', 'supplier')
    search_fields = ('supplier__name', 'reference')
    ordering = ('-payment_date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Invoice)
class InvoiceAdmin(FinancialRecordAdmin):
    list_display = ('invoice_number', 'sale', 'invoice_date', 'due_date', 'status', 'create_at')
    list_filter = ('status', 'invoice_date')
    search_fields = ('invoice_number', 'sale__id')
    ordering = ('-invoice_date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)


# System Settings Admin
@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    """Admin pour les paramètres système (instance unique)."""
    list_display = ('company_name', 'company_phone', 'company_email', 'currency_symbol', 'updated_at')
    readonly_fields = ('updated_at',)

    fieldsets = (
        (_('Informations de l\'entreprise'), {
            'fields': (
                'company_name', 'company_address', 'company_phone',
                'company_email', 'company_website', 'company_logo',
            )
        }),
        (_('Informations fiscales / légales'), {
            'fields': ('tax_id', 'trade_register', 'tva_accounting_mode', 'enable_tva_accounting'),
        }),
        (_('Paramètres monétaires'), {
            'fields': ('currency_symbol', 'currency_code'),
        }),
        (_('Paramètres de tickets / reçus'), {
            'fields': ('receipt_header', 'receipt_footer'),
        }),
        (_('Paramètres de stock'), {
            'fields': ('low_stock_threshold',),
        }),
        (_('Paramètres par défaut'), {
            'fields': ('default_supply_expense_type',),
        }),
        (_('Métadonnées'), {
            'fields': ('updated_at',),
        }),
    )

    def has_add_permission(self, request):
        """Empêcher la création de plusieurs instances."""
        return not SystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Empêcher la suppression de l'instance unique."""
        return False



# Phase 4 — TVA, Rapprochement, Clôture
@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ('name', 'rate', 'is_default', 'is_active', 'create_at')
    list_filter = ('is_default', 'is_active')
    search_fields = ('name',)
    ordering = ('rate',)


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = ('statement_date', 'account', 'description', 'amount', 'statement_type', 'is_reconciled', 'create_at')
    list_filter = ('statement_type', 'is_reconciled', 'account')
    search_fields = ('description', 'reference')
    ordering = ('-statement_date',)


@admin.register(ExerciseClosing)
class ExerciseClosingAdmin(admin.ModelAdmin):
    list_display = ('exercise', 'closed_at', 'closed_by', 'result_amount', 'new_exercise')
    list_filter = ('closed_at',)
    search_fields = ('exercise__id',)
    ordering = ('-closed_at',)


# Phase 5 — Modules applicatifs
@admin.register(AppModule)
class AppModuleAdmin(admin.ModelAdmin):
    """Admin pour les modules applicatifs."""
    list_display = ('code', 'name', 'icon', 'order', 'is_active')
    list_filter = ('is_active',)
    list_editable = ('order', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('order',)
