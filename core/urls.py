from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('sales/', views.sales, name='sales'),
    path('products/', views.products, name='products'),
    path('inventory/', views.inventory, name='inventory'),
    path('clients/', views.clients, name='clients'),
    path('suppliers/', views.suppliers, name='suppliers'),
    path('expenses/', views.expenses, name='expenses'),
    path('staff/', views.staff, name='staff'),
    path('reports/', views.reports, name='reports'),
    path('settings/', views.settings, name='settings'),
]
