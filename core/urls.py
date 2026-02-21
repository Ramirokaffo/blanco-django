from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
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
    path('contacts/suppliers/add/', views.add_supplier, name='add_supplier'),
    path('contacts/suppliers/<int:pk>/edit/', views.edit_supplier, name='edit_supplier'),
    path('expenses/', views.expenses, name='expenses'),
    path('expenses/add/', views.add_expense, name='add_expense'),
    path('daily/summary/', views.get_daily_summary, name='get_daily_summary'),
    path('daily/close/', views.close_daily, name='close_daily'),
    path('reports/', views.reports, name='reports'),
    path('settings/', views.settings, name='settings'),
    path('settings/migration/', views.data_migration, name='data_migration'),
]
