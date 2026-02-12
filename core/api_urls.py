from django.urls import path
from . import api_views

app_name = 'api'

urlpatterns = [
    path('products/search/', api_views.search_products, name='search_products'),
    path('products/<int:product_id>/', api_views.get_product_details, name='product_details'),
    path('sales/create/', api_views.create_sale, name='create_sale'),
    path('sales/search/', api_views.search_sales, name='search_sales'),
    path('sales/<int:sale_id>/', api_views.get_sale_details, name='sale_details'),
]

