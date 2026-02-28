from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard_alias'),
    path('sales/', views.sales, name='sales'),
    path('sales/history/', views.sales_history, name='sales_history'),
    path('products/', views.products, name='products'),
    path('inventory/', views.inventory, name='inventory'),
    path('inventory/add/', views.add_inventory, name='add_inventory'),
    path('inventory/history/', views.inventory_history, name='inventory_history'),
    path('inventory/close/', views.close_inventory_summary, name='close_inventory_summary'),
    path('inventory/close/confirm/', views.close_inventory_confirm, name='close_inventory_confirm'),
    path('supplies/', views.supplies, name='supplies'),
    path('supplies/add/', views.add_supply, name='add_supply'),
    path('contacts/', views.contacts, name='contacts'),
    path('contacts/clients/add/', views.add_client, name='add_client'),
    path('contacts/clients/<int:pk>/edit/', views.edit_client, name='edit_client'),
    path('suppliers/', views.suppliers_list, name='suppliers'),
    path('suppliers/add/', views.add_supplier, name='add_supplier'),
    path('suppliers/<int:pk>/edit/', views.edit_supplier, name='edit_supplier'),
    path('expenses-recipe/', views.expenses, name='expenses'),
    path('expenses/add/', views.add_expense, name='add_expense'),
    path('expenses/add/ajax/', views.add_expense_ajax, name='add_expense_ajax'),
    path('recipes/add/', views.add_recipe, name='add_recipe'),
    path('daily/summary/', views.get_daily_summary, name='get_daily_summary'),
    path('daily/close/', views.close_daily, name='close_daily'),
    path('reports/', views.reports, name='reports'),
    path('settings/', views.settings, name='settings'),
    path('settings/migration/', views.data_migration, name='data_migration'),

    # Comptabilité
    path('accounting/journal/', views.accounting_journal, name='accounting_journal'),
    path('accounting/journal/add/', views.accounting_add_entry, name='accounting_add_entry'),
    path('accounting/ledger/', views.accounting_general_ledger, name='accounting_ledger'),
    path('accounting/balance/', views.accounting_trial_balance, name='accounting_balance'),
    path('accounting/chart/', views.accounting_chart_of_accounts, name='accounting_chart'),
    path('accounting/chart/export/', views.export_chart_of_accounts, name='export_chart_of_accounts'),
    path('accounting/chart/import/', views.import_chart_of_accounts, name='import_chart_of_accounts'),

    # Phase 2 — Trésorerie, Paiements, Factures
    path('accounting/treasury/', views.treasury_dashboard, name='treasury_dashboard'),
    path('accounting/credit-sales/', views.credit_sales_list, name='credit_sales'),
    path('accounting/credit-sales/<int:credit_sale_id>/payment/', views.record_credit_payment, name='record_credit_payment'),
    path('accounting/supplier-payments/', views.supplier_payments_list, name='supplier_payments'),
    path('accounting/supplier-payments/add/', views.add_supplier_payment, name='add_supplier_payment'),
    path('accounting/supply/<int:supply_id>/payment/', views.record_supply_payment, name='record_supply_payment'),
    path('accounting/invoices/', views.invoices_list, name='invoices'),
    path('accounting/invoices/generate/<int:sale_id>/', views.generate_invoice, name='generate_invoice'),

    # Phase 3 — Rapports financiers
    path('accounting/income-statement/', views.income_statement, name='income_statement'),
    path('accounting/balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('accounting/aged-balance/', views.aged_balance, name='aged_balance'),
    path('accounting/product-margins/', views.product_margins, name='product_margins'),
    path('accounting/export/<str:report_type>/', views.export_report_csv, name='export_report_csv'),

    # Phase 4 — TVA, Rapprochement bancaire, Clôture d'exercice
    path('accounting/vat-declaration/', views.vat_declaration, name='vat_declaration'),
    path('accounting/bank-reconciliation/', views.bank_reconciliation, name='bank_reconciliation'),
    path('accounting/reconcile/', views.reconcile_entry, name='reconcile_entry'),
    path('accounting/unreconcile/', views.unreconcile_entry, name='unreconcile_entry'),
    path('accounting/exercise-closing/', views.exercise_closing_view, name='exercise_closing'),
    path('accounting/exercise-closing/close/', views.close_exercise_action, name='close_exercise_action'),
]
