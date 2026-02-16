from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('sales/', views.sales, name='sales'),
    path('products/', views.products, name='products'),
    path('inventory/', views.inventory, name='inventory'),
    path('supplies/', views.supplies, name='supplies'),
    path('contacts/', views.contacts, name='contacts'),
    path('expenses/', views.expenses, name='expenses'),
    path('reports/', views.reports, name='reports'),
    path('settings/', views.settings, name='settings'),
]
