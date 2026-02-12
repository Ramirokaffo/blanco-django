from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from core.models.sale_models import Sale
from core.models.user_models import Client
from core.models.accounting_models import Daily
from core.services.daily_service import DailyService
# from core.models.client_models import Client

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
    """Vue de la page des produits"""
    context = {
        'page_title': 'Produits'
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
def clients(request):
    """Vue de la page des clients"""
    context = {
        'page_title': 'Clients'
    }
    return render(request, 'core/clients.html', context)


@login_required
def suppliers(request):
    """Vue de la page des fournisseurs"""
    context = {
        'page_title': 'Fournisseurs'
    }
    return render(request, 'core/suppliers.html', context)


@login_required
def expenses(request):
    """Vue de la page des dépenses"""
    context = {
        'page_title': 'Dépenses'
    }
    return render(request, 'core/expenses.html', context)


@login_required
def staff(request):
    """Vue de la page du personnel"""
    context = {
        'page_title': 'Personnel'
    }
    return render(request, 'core/staff.html', context)


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
