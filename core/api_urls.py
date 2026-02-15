from django.urls import path

from .api_views import (
    auth_views,
    staff_views,
    product_views,
    sale_views,
    inventory_views,
    reference_views,
    utils_views,
)

app_name = 'api'

urlpatterns = [
    # ── Auth ────────────────────────────────────────────────────────
    # Flask: GET /login/<login>/<password>
    path('auth/login/', auth_views.login, name='login'),

    # ── Staff / Users ──────────────────────────────────────────────
    # Flask: GET  /get_user_by_id/<id>
    path('staff/<int:user_id>/', staff_views.get_user_by_id, name='get_user_by_id'),
    # Flask: GET  /get_staff_by_login/<login>
    path('staff/by-username/<str:login>/', staff_views.get_staff_by_login, name='get_staff_by_login'),
    # Flask: POST /create_user
    path('staff/', staff_views.create_user, name='create_user'),
    # Flask: POST /update_user
    path('staff/<int:user_id>/update/', staff_views.update_user, name='update_user'),

    # ── Products ───────────────────────────────────────────────────
    # Flask: GET /get_product_list/<page>/<count>
    path('products/list/', product_views.get_product_list, name='product_list'),
    # Flask: GET /search_product
    path('products/search/', product_views.search_products, name='search_products'),
    # Flask: GET /get_product_by_id/<product_id>
    path('products/<int:product_id>/', product_views.get_product_by_id, name='product_by_id'),
    # Flask: GET /get_product_by_code/<product_code>
    path('products/by-code/<str:product_code>/', product_views.get_product_by_code, name='product_by_code'),
    # Flask: GET /get_product_by_name/<str:product_name>
    path('products/by-name/<str:product_name>/', product_views.get_product_by_name, name='product_by_name'),
    # Flask: POST /create_product
    path('products/', product_views.create_product, name='create_product'),

    # ── Images ─────────────────────────────────────────────────────
    # Flask: GET /image/<folder>/<image>
    path('images/<str:folder>/<str:image>/', product_views.get_image, name='get_image'),

    # ── Reference data ─────────────────────────────────────────────
    # Flask: GET /get_category
    path('categories/', reference_views.get_categories, name='categories'),
    # Flask: GET /get_rayon
    path('rayons/', reference_views.get_rayons, name='rayons'),
    # Flask: GET /get_gamme
    path('gammes/', reference_views.get_gammes, name='gammes'),
    # Flask: GET /get_grammage_type
    path('grammage-types/', reference_views.get_grammage_types, name='grammage_types'),

    # ── Sales ──────────────────────────────────────────────────────
    # Flask: POST /sale
    path('sales/', sale_views.create_sale, name='create_sale'),
    # Recherche de ventes
    path('sales/search/', sale_views.search_sales, name='search_sales'),
    # Détails d'une vente
    path('sales/<int:sale_id>/', sale_views.get_sale_details, name='sale_details'),

    # ── Inventory ──────────────────────────────────────────────────
    # Flask: POST /create_inventory
    path('inventory/', inventory_views.create_inventory, name='create_inventory'),

    # ── Utils ──────────────────────────────────────────────────────
    # Flask: GET /test_connexion
    path('test-connection/', utils_views.test_connection, name='test_connection'),

]

