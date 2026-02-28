"""
Django admin configuration for core models.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
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
        ('Informations supplémentaires', {
            'fields': ('firstname', 'lastname', 'phone_number', 'role', 'gender', 'profil', 'delete_at')
        }),
        ('Modules autorisés', {
            'fields': ('allowed_modules',),
            'description': 'Sélectionnez les modules auxquels cet utilisateur a accès. Les superusers ont accès à tout.'
        }),
    )

    # Ajouter les champs personnalisés au formulaire de création
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informations supplémentaires', {
            'fields': ('firstname', 'lastname', 'phone_number', 'role', 'gender', 'profil')
        }),
    )

    filter_horizontal = ('allowed_modules', 'groups', 'user_permissions')


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
    list_display = ('code', 'name', 'category', 'stock', 'stock_limit', "actual_price", "last_purchase_price", 'is_price_reducible')
    list_filter = ('category', 'gamme', 'rayon', 'is_price_reducible', 'create_at')
    search_fields = ('code', 'name', 'description', 'brand')
    list_editable = ['stock_limit', 'actual_price', 'is_price_reducible', "last_purchase_price"]
    ordering = ('name',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'image_path', 'is_primary', 'create_at')
    list_filter = ('is_primary', 'create_at')
    search_fields = ('product__name', 'image_path')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Sale Models Admin
@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'total', 'client', 'staff', 'is_paid', 'is_credit', 'daily', 'create_at')
    list_filter = ('is_paid', 'is_credit', 'create_at')
    search_fields = ('client__firstname', 'client__lastname', 'staff__username')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(SaleProduct)
class SaleProductAdmin(admin.ModelAdmin):
    list_display = ('sale', 'product', 'quantity', "unit_price", 'get_subtotal')
    list_filter = ('create_at',)
    search_fields = ('sale__id', 'product__name')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(CreditSale)
class CreditSaleAdmin(admin.ModelAdmin):
    list_display = ('sale', 'amount_paid', 'amount_remaining', 'due_date', 'is_fully_paid', 'create_at')
    list_filter = ('is_fully_paid', 'due_date', 'create_at')
    search_fields = ('sale__id',)
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('sale', 'value', 'reason', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('sale__id', 'reason')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


# Inventory Models Admin
@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ('product', 'supplier', 'quantity', "purchase_cost", 'selling_price', 'total_price', 'expiration_date', 'create_at')
    list_filter = ('expiration_date', 'create_at')
    search_fields = ('product__name', 'supplier__name')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


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
    model = JournalEntryLine
    extra = 0
    readonly_fields = ('create_at',)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('code',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('reference', 'date', 'journal', 'description', 'is_validated', 'exercise')
    list_filter = ('journal', 'is_validated', 'date')
    search_fields = ('reference', 'description')
    ordering = ('-date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)
    inlines = [JournalEntryLineInline]


@admin.register(JournalEntryLine)
class JournalEntryLineAdmin(admin.ModelAdmin):
    list_display = ('entry', 'account', 'debit', 'credit', 'description')
    list_filter = ('account',)
    search_fields = ('entry__reference', 'account__code', 'description')
    ordering = ('-entry__date',)
    readonly_fields = ('create_at', 'delete_at',)


# Phase 2 — Paiements & Factures
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('credit_sale', 'amount', 'payment_method', 'payment_date', 'staff', 'create_at')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('credit_sale__sale__id', 'reference')
    ordering = ('-payment_date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'amount', 'payment_method', 'payment_date', 'staff', 'create_at')
    list_filter = ('payment_method', 'payment_date', 'supplier')
    search_fields = ('supplier__name', 'reference')
    ordering = ('-payment_date', '-create_at')
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
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
        ('Informations de l\'entreprise', {
            'fields': (
                'company_name', 'company_address', 'company_phone',
                'company_email', 'company_website', 'company_logo',
            )
        }),
        ('Informations fiscales / légales', {
            'fields': ('tax_id', 'trade_register', 'tva_accounting_mode', 'enable_tva_accounting'),
        }),
        ('Paramètres monétaires', {
            'fields': ('currency_symbol', 'currency_code'),
        }),
        ('Paramètres de tickets / reçus', {
            'fields': ('receipt_header', 'receipt_footer'),
        }),
        ('Paramètres de stock', {
            'fields': ('low_stock_threshold',),
        }),
        ('Paramètres par défaut', {
            'fields': ('default_supply_expense_type',),
        }),
        ('Métadonnées', {
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
