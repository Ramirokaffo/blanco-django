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
    Supply, Inventory, DailyInventory,
    # Accounting models
    Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense
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
    )

    # Ajouter les champs personnalisés au formulaire de création
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informations supplémentaires', {
            'fields': ('firstname', 'lastname', 'phone_number', 'role', 'gender', 'profil')
        }),
    )


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('get_full_name', 'phone_number', 'email', 'gender', 'create_at')
    list_filter = ('gender', 'create_at')
    search_fields = ('firstname', 'lastname', 'phone_number', 'email')
    ordering = ('-create_at',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('get_full_name', 'phone_number', 'email', 'gender', 'create_at')
    list_filter = ('gender', 'create_at')
    search_fields = ('firstname', 'lastname', 'phone_number', 'email')
    ordering = ('-create_at',)


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
    list_display = ('code', 'name', 'category', 'stock', 'stock_limit', 'actual_price', 'is_price_reducible')
    list_filter = ('category', 'gamme', 'rayon', 'is_price_reducible', 'create_at')
    search_fields = ('code', 'name', 'description', 'brand')
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
    list_display = ('sale', 'product', 'quantity', 'unit_price', 'get_subtotal')
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
    list_display = ('product', 'supplier', 'quantity', 'unit_price', 'total_price', 'expiration_date', 'create_at')
    list_filter = ('expiration_date', 'create_at')
    search_fields = ('product__name', 'supplier__firstname', 'supplier__lastname')
    ordering = ('-create_at',)
    readonly_fields = ('create_at', 'delete_at',)


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity_counted', 'quantity_system', 'difference', 'staff', 'create_at')
    list_filter = ('create_at',)
    search_fields = ('product__name', 'staff__username')
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
