"""
Models package for the core application.
Organized by domain for better maintainability.
"""

from .base_models import *
from .user_models import *
from .product_models import *
from .sale_models import *
from .inventory_models import *
from .accounting_models import *
from .settings_models import *

__all__ = [
    # Base models
    'BaseUser',

    # User models
    'CustomUser',
    'Staff',  # Alias pour CustomUser (compatibilité)
    'Client',
    'Supplier',

    # Product models
    'Category',
    'Gamme',
    'Rayon',
    'GrammageType',
    'Product',
    'ProductImage',

    # Sale models
    'Sale',
    'SaleProduct',
    'CreditSale',
    'Refund',

    # Inventory models
    'Supply',
    'Inventory',
    'InventorySnapshot',
    'DailyInventory',

    # Accounting models
    'Account',
    'JournalEntry',
    'JournalEntryLine',
    'Exercise',
    'Daily',
    'ExpenseType',
    'RecipeType',
    'DailyExpense',
    'DailyRecipe',
    'ProductExpense',
    'Payment',
    'SupplierPayment',
    'Invoice',
    'PAYMENT_METHOD_CHOICES',
    'PAYMENT_METHOD_ACCOUNT_MAP',
    'TaxRate',
    'BankStatement',
    'ExerciseClosing',

    # Settings models
    'SystemSettings',
]

