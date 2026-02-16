from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, F
from core.models.sale_models import Sale
from core.models.user_models import Client, Supplier, CustomUser
from core.models.accounting_models import Daily
from core.models.product_models import Product, Category, Gamme, Rayon
from core.models.inventory_models import Supply
from core.services.daily_service import DailyService

# Create your views here.

@login_required
def dashboard(request):
    """Vue du tableau de bord"""
    context = {
        'page_title': 'Tableau de bord'
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def sales(request):
    """Vue de la page des ventes"""
    from django.db.models import Sum

    # Récupérer le Daily actif (non fermé)
    # current_daily = Daily.objects.filter(end_date__isnull=True).order_by('-start_date').first()
    current_daily = DailyService().get_or_create_active_daily()

    if current_daily:
        # Récupérer uniquement les ventes du Daily en cours
        sales_list = Sale.objects.select_related('client', 'staff', 'daily').filter(
            delete_at__isnull=True,
            daily=current_daily
        ).order_by('-create_at')

        # Calculer la recette totale du jour
        total_revenue = sales_list.aggregate(total=Sum('total'))['total'] or 0
    else:
        # Aucun Daily actif
        sales_list = Sale.objects.none()
        total_revenue = 0

    # Récupérer tous les clients actifs
    clients_list = Client.objects.filter(delete_at__isnull=True).order_by('firstname')

    context = {
        'page_title': 'Ventes',
        'sales': sales_list,
        'clients': clients_list,
        'current_daily': current_daily,
        'total_revenue': total_revenue,
    }
    return render(request, 'core/sales.html', context)


@login_required
def products(request):
    """Vue de la page des produits avec pagination et filtres"""
    # Récupérer les paramètres de filtre
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '')
    gamme_id = request.GET.get('gamme', '')
    rayon_id = request.GET.get('rayon', '')
    stock_status = request.GET.get('stock_status', '')
    page_number = request.GET.get('page', 1)

    # Queryset de base : produits actifs (non supprimés)
    queryset = Product.objects.filter(
        delete_at__isnull=True,
    ).select_related('category', 'gamme', 'rayon', 'grammage_type')

    # Appliquer les filtres
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(code__icontains=search) | Q(brand__icontains=search)
        )
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    if gamme_id:
        queryset = queryset.filter(gamme_id=gamme_id)
    if rayon_id:
        queryset = queryset.filter(rayon_id=rayon_id)
    if stock_status == 'low':
        queryset = queryset.filter(stock__lte=F('stock_limit'))
    elif stock_status == 'out':
        queryset = queryset.filter(stock=0)
    elif stock_status == 'in':
        queryset = queryset.filter(stock__gt=0)

    # Pagination
    paginator = Paginator(queryset.order_by('name'), 20)
    page_obj = paginator.get_page(page_number)

    # Données pour les filtres (dropdowns)
    categories = Category.objects.filter(delete_at__isnull=True).order_by('name')
    gammes = Gamme.objects.filter(delete_at__isnull=True).order_by('name')
    rayons = Rayon.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Produits',
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'categories': categories,
        'gammes': gammes,
        'rayons': rayons,
        # Conserver les valeurs des filtres pour le template
        'current_search': search,
        'current_category': category_id,
        'current_gamme': gamme_id,
        'current_rayon': rayon_id,
        'current_stock_status': stock_status,
        'total_count': paginator.count,
    }
    return render(request, 'core/products.html', context)


@login_required
def inventory(request):
    """Vue de la page de l'inventaire"""
    context = {
        'page_title': 'Inventaire'
    }
    return render(request, 'core/inventory.html', context)


@login_required
def contacts(request):
    """Vue combinée : Clients, Fournisseurs, Personnel avec sous-onglets"""
    tab = request.GET.get('tab', 'clients')
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    if tab == 'suppliers':
        queryset = Supplier.objects.filter(delete_at__isnull=True)
        if search:
            queryset = queryset.filter(
                Q(firstname__icontains=search) | Q(lastname__icontains=search) | Q(phone_number__icontains=search)
            )
        queryset = queryset.order_by('firstname', 'lastname')
    elif tab == 'staff':
        queryset = CustomUser.objects.filter(delete_at__isnull=True, is_active=True)
        if search:
            queryset = queryset.filter(
                Q(firstname__icontains=search) | Q(lastname__icontains=search) | Q(username__icontains=search)
            )
        queryset = queryset.order_by('firstname', 'lastname')
    else:
        tab = 'clients'
        queryset = Client.objects.filter(delete_at__isnull=True)
        if search:
            queryset = queryset.filter(
                Q(firstname__icontains=search) | Q(lastname__icontains=search) | Q(phone_number__icontains=search)
            )
        queryset = queryset.order_by('firstname', 'lastname')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Contacts',
        'current_tab': tab,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/contacts.html', context)


@login_required
def supplies(request):
    """Vue de la page des approvisionnements avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    supplier_id = request.GET.get('supplier', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)

    queryset = Supply.objects.filter(
        delete_at__isnull=True,
    ).select_related('product', 'supplier', 'staff', 'daily')

    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search) | Q(product__code__icontains=search)
        )
    if supplier_id:
        queryset = queryset.filter(supplier_id=supplier_id)
    if date_from:
        queryset = queryset.filter(create_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(create_at__date__lte=date_to)

    queryset = queryset.order_by('-create_at')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    suppliers_list = Supplier.objects.filter(delete_at__isnull=True).order_by('firstname')

    context = {
        'page_title': 'Approvisionnement',
        'page_obj': page_obj,
        'supplies': page_obj.object_list,
        'suppliers': suppliers_list,
        'current_search': search,
        'current_supplier': supplier_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_count': paginator.count,
    }
    return render(request, 'core/supplies.html', context)


@login_required
def expenses(request):
    """Vue de la page des dépenses"""
    context = {
        'page_title': 'Dépenses'
    }
    return render(request, 'core/expenses.html', context)


@login_required
def reports(request):
    """Vue de la page des rapports"""
    context = {
        'page_title': 'Rapports'
    }
    return render(request, 'core/reports.html', context)


@login_required
def settings(request):
    """Vue de la page des paramètres"""
    context = {
        'page_title': 'Paramètres'
    }
    return render(request, 'core/settings.html', context)
