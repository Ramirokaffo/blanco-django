from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F, Sum, Count
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from core.models.sale_models import Sale, SaleProduct, CreditSale
from core.models.user_models import Client, Supplier, CustomUser
from core.models.accounting_models import (
    Daily, DailyExpense, DailyRecipe, ExpenseType, Exercise,
    Account, Payment, RecipeType, SupplierPayment, Invoice,
    TaxRate, BankStatement, ExerciseClosing,
)
from core.models.product_models import Product, Category, Gamme, Rayon
from core.models.inventory_models import Supply, Inventory, InventorySnapshot, DailyInventory, CreditSupply, PaymentSchedule
from core.services.daily_service import DailyService
from core.forms import (
    SupplyForm, ExpenseForm, ClientForm, SupplierForm, InventoryForm,
    DataMigrationForm, PaymentForm, SupplierPaymentForm,
)
from core.services.excercise_service import ExerciseService
from core.services.accounting_service import AccountingService
from core.decorators import module_required



def login_view(request):
    """Vue de connexion personnalisée (accessible aux non-admins)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                auth_login(request, user)
                next_url = request.GET.get('next') or request.POST.get('next') or '/'
                return redirect(next_url)
            else:
                error = "Nom d'utilisateur ou mot de passe incorrect."
        else:
            error = "Veuillez remplir tous les champs."

    return render(request, 'core/login.html', {
        'error': error,
        'next': request.GET.get('next', ''),
    })


def logout_view(request):
    """Déconnexion et redirection vers la page de login."""
    auth_logout(request)
    return redirect('login')

@login_required
@module_required('dashboard')
def dashboard(request):
    """Vue du tableau de bord avec les statistiques de la journée"""
    from core.models.settings_models import SystemSettings

    current_daily = DailyService.get_or_create_active_daily()
    settings_obj = SystemSettings.get_settings()

    # ── Ventes du jour ───────────────────────────────────────────
    today_sales = Sale.objects.filter(
        daily=current_daily, delete_at__isnull=True
    )
    total_revenue = today_sales.aggregate(total=Sum('total'))['total'] or 0
    sales_count = today_sales.count()

    # Ventes annulées du jour
    cancelled_sales_count = Sale.objects.filter(
        daily=current_daily, delete_at__isnull=False
    ).count()

    # Produits vendus (somme des quantités)
    products_sold_count = SaleProduct.objects.filter(
        sale__daily=current_daily, sale__delete_at__isnull=True, delete_at__isnull=True
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # ── Dépenses du jour ─────────────────────────────────────────
    total_expenses = DailyExpense.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ── Recettes additionnelles du jour ──────────────────────────
    total_recipes = DailyRecipe.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Solde net = ventes + recettes - dépenses
    net_balance = float(total_revenue) + float(total_recipes) - float(total_expenses)

    # ── Fond de caisse précédent ─────────────────────────────────
    previous_inventory = DailyInventory.objects.filter(
        delete_at__isnull=True
    ).exclude(daily=current_daily).order_by('-create_at').first()
    previous_cash_float = float(previous_inventory.cash_float) if previous_inventory else 0

    # Cash attendu = fond de caisse + ventes + recettes - dépenses
    expected_cash = previous_cash_float + float(total_revenue) + float(total_recipes) - float(total_expenses)

    # ── Fréquence clients / heure ────────────────────────────────
    if sales_count > 0:
        first_sale = today_sales.order_by('create_at').first()
        now = timezone.now()
        if first_sale:
            elapsed = (now - first_sale.create_at).total_seconds() / 3600
            frequency = round(sales_count / elapsed, 1) if elapsed > 0 else sales_count
        else:
            frequency = 0
    else:
        frequency = 0

    # ── Comparaison avec la veille ───────────────────────────────
    previous_daily = Daily.objects.filter(
        end_date__isnull=False, delete_at__isnull=True
    ).order_by('-end_date').first()

    if previous_daily:
        yesterday_revenue = Sale.objects.filter(
            daily=previous_daily, delete_at__isnull=True
        ).aggregate(total=Sum('total'))['total'] or 0
        yesterday_sales_count = Sale.objects.filter(
            daily=previous_daily, delete_at__isnull=True
        ).count()
    else:
        yesterday_revenue = 0
        yesterday_sales_count = 0

    # Taux de variation (%)
    if yesterday_revenue and float(yesterday_revenue) > 0:
        revenue_trend = round((float(total_revenue) - float(yesterday_revenue)) / float(yesterday_revenue) * 100, 1)
    else:
        revenue_trend = None  # Pas de comparaison possible

    # ── Produits en alerte stock ─────────────────────────────────
    low_stock_threshold = settings_obj.low_stock_threshold
    low_stock_products = Product.objects.filter(
        delete_at__isnull=True,
        stock__lte=F('stock_limit')
    ).exclude(stock_limit__isnull=True).order_by('stock')[:10]

    out_of_stock_count = Product.objects.filter(
        delete_at__isnull=True, stock=0
    ).count()

    low_stock_count = Product.objects.filter(
        delete_at__isnull=True,
        stock__lte=F('stock_limit'),
        stock__gt=0,
    ).exclude(stock_limit__isnull=True).count()

    # ── Approvisionnements du jour ───────────────────────────────
    today_supplies_count = Supply.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).count()
    today_supplies_total = Supply.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('total_price'))['total'] or 0

    # ── Dernières ventes ─────────────────────────────────────────
    recent_sales = today_sales.select_related('client', 'staff').order_by('-create_at')[:8]

    # ── Total produits ───────────────────────────────────────────
    total_products = Product.objects.filter(delete_at__isnull=True).count()

    context = {
        'page_title': 'Tableau de bord',
        'current_daily': current_daily,
        # KPI principaux
        'total_revenue': total_revenue,
        'sales_count': sales_count,
        'total_expenses': total_expenses,
        'total_recipes': total_recipes,
        'net_balance': net_balance,
        'expected_cash': expected_cash,
        'previous_cash_float': previous_cash_float,
        'products_sold_count': products_sold_count,
        'cancelled_sales_count': cancelled_sales_count,
        'frequency': frequency,
        # Comparaison veille
        'yesterday_revenue': yesterday_revenue,
        'yesterday_sales_count': yesterday_sales_count,
        'revenue_trend': revenue_trend,
        # Stock
        'low_stock_products': low_stock_products,
        'out_of_stock_count': out_of_stock_count,
        'low_stock_count': low_stock_count,
        'total_products': total_products,
        # Approvisionnements
        'today_supplies_count': today_supplies_count,
        'today_supplies_total': today_supplies_total,
        # Ventes récentes
        'recent_sales': recent_sales,
        # Devise
        'currency': settings_obj.currency_symbol,
    }
    return render(request, 'core/dashboard.html', context)


@login_required
@module_required('dashboard')
def statistics(request):
    """Vue structurée des statistiques globales du système."""
    from core.models.settings_models import SystemSettings

    def to_percentage(value, total):
        return round((value / total) * 100, 1) if total else 0

    settings_obj = SystemSettings.get_settings()
    current_daily = DailyService.get_or_create_active_daily()
    today = timezone.localdate()

    sales_queryset = Sale.objects.filter(delete_at__isnull=True)
    sale_products_queryset = SaleProduct.objects.filter(
        delete_at__isnull=True,
        sale__delete_at__isnull=True,
    )
    products_queryset = Product.objects.filter(delete_at__isnull=True)
    supplies_queryset = Supply.objects.filter(delete_at__isnull=True)
    expenses_queryset = DailyExpense.objects.filter(delete_at__isnull=True)
    recipes_queryset = DailyRecipe.objects.filter(delete_at__isnull=True)
    credit_sales_queryset = CreditSale.objects.filter(delete_at__isnull=True, sale__delete_at__isnull=True)
    credit_supplies_queryset = CreditSupply.objects.filter(delete_at__isnull=True, supply__delete_at__isnull=True)
    invoices_queryset = Invoice.objects.filter(delete_at__isnull=True)
    payments_queryset = Payment.objects.filter(delete_at__isnull=True)
    supplier_payments_queryset = SupplierPayment.objects.filter(delete_at__isnull=True)
    inventories_queryset = Inventory.objects.filter(delete_at__isnull=True)
    overdue_schedules = PaymentSchedule.objects.filter(
        delete_at__isnull=True,
        due_date__lt=today,
    ).exclude(status='PAID').select_related(
        'credit_sale__sale__client',
        'credit_supply__supply__supplier',
    ).order_by('due_date')[:6]

    today_sales = sales_queryset.filter(daily=current_daily) if current_daily else Sale.objects.none()
    today_supplies = supplies_queryset.filter(daily=current_daily) if current_daily else Supply.objects.none()
    today_expenses_queryset = expenses_queryset.filter(daily=current_daily) if current_daily else DailyExpense.objects.none()
    today_recipes_queryset = recipes_queryset.filter(daily=current_daily) if current_daily else DailyRecipe.objects.none()

    total_revenue = sales_queryset.aggregate(total=Sum('total'))['total'] or 0
    sales_count = sales_queryset.count()
    products_sold_count = sale_products_queryset.aggregate(total=Sum('quantity'))['total'] or 0
    average_ticket = (total_revenue / sales_count) if sales_count else 0
    paid_sales_count = sales_queryset.filter(is_paid=True).count()
    credit_sales_count = sales_queryset.filter(is_credit=True).count()
    unpaid_sales_count = sales_queryset.filter(is_paid=False).count()

    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or 0
    total_recipes = recipes_queryset.aggregate(total=Sum('amount'))['total'] or 0
    net_result = total_revenue + total_recipes - total_expenses

    total_supplies = supplies_queryset.aggregate(total=Sum('total_price'))['total'] or 0
    supplies_count = supplies_queryset.count()
    receivables_total = credit_sales_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    supplier_debt_total = credit_supplies_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    payments_received_total = payments_queryset.aggregate(total=Sum('amount'))['total'] or 0
    supplier_payments_total = supplier_payments_queryset.aggregate(total=Sum('amount'))['total'] or 0

    total_products = products_queryset.count()
    in_stock_count = products_queryset.filter(stock__gt=0).count()
    out_of_stock_count = products_queryset.filter(stock=0).count()
    low_stock_queryset = products_queryset.filter(stock__lte=F('stock_limit')).exclude(stock_limit__isnull=True)
    low_stock_count = low_stock_queryset.filter(stock__gt=0).count()
    stock_alert_count = low_stock_queryset.count()
    total_stock_units = products_queryset.aggregate(total=Sum('stock'))['total'] or 0
    categories_count = Category.objects.filter(delete_at__isnull=True).count()
    gammes_count = Gamme.objects.filter(delete_at__isnull=True).count()
    rayons_count = Rayon.objects.filter(delete_at__isnull=True).count()
    products_with_category_count = products_queryset.filter(
        category__isnull=False,
        category__delete_at__isnull=True,
    ).count()
    products_with_gamme_count = products_queryset.filter(
        gamme__isnull=False,
        gamme__delete_at__isnull=True,
    ).count()
    products_with_rayon_count = products_queryset.filter(
        rayon__isnull=False,
        rayon__delete_at__isnull=True,
    ).count()

    clients_count = Client.objects.filter(delete_at__isnull=True).count()
    staff_count = CustomUser.objects.filter(delete_at__isnull=True).count()
    suppliers_count = Supplier.objects.filter(delete_at__isnull=True).count()
    active_users_count = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).count()
    inactive_users_count = CustomUser.objects.filter(delete_at__isnull=True, is_active=False).count()
    open_dailies_count = Daily.objects.filter(delete_at__isnull=True, end_date__isnull=True).count()
    inventory_sessions_count = inventories_queryset.count()
    valid_inventory_units = inventories_queryset.aggregate(total=Sum('valid_product_count'))['total'] or 0
    invalid_inventory_units = inventories_queryset.aggregate(total=Sum('invalid_product_count'))['total'] or 0
    inventory_snapshot_count = InventorySnapshot.objects.filter(delete_at__isnull=True).count()

    today_revenue = today_sales.aggregate(total=Sum('total'))['total'] or 0
    today_sales_count = today_sales.count()
    today_products_sold = sale_products_queryset.filter(sale__daily=current_daily).aggregate(total=Sum('quantity'))['total'] or 0
    today_expenses = today_expenses_queryset.aggregate(total=Sum('amount'))['total'] or 0
    today_recipes = today_recipes_queryset.aggregate(total=Sum('amount'))['total'] or 0
    today_supplies_count = today_supplies.count()
    today_supplies_total = today_supplies.aggregate(total=Sum('total_price'))['total'] or 0
    today_net = today_revenue + today_recipes - today_expenses

    invoice_total = invoices_queryset.count()
    paid_invoices_count = invoices_queryset.filter(status='PAID').count()
    sent_invoices_count = invoices_queryset.filter(status='SENT').count()
    draft_invoices_count = invoices_queryset.filter(status='DRAFT').count()
    cancelled_invoices_count = invoices_queryset.filter(status='CANCELLED').count()

    recent_sales = sales_queryset.select_related('client', 'staff').order_by('-create_at')[:6]
    low_stock_products = low_stock_queryset.order_by('stock', 'name')[:6]
    top_products = products_queryset.filter(
        sale_products__delete_at__isnull=True,
        sale_products__sale__delete_at__isnull=True,
    ).annotate(
        total_quantity=Sum('sale_products__quantity'),
        sales_frequency=Count('sale_products__sale', distinct=True),
    ).order_by('-total_quantity', 'name')[:6]

    context = {
        'page_title': 'Statistiques',
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'current_daily': current_daily,
        'total_revenue': total_revenue,
        'sales_count': sales_count,
        'products_sold_count': products_sold_count,
        'average_ticket': average_ticket,
        'paid_sales_count': paid_sales_count,
        'credit_sales_count': credit_sales_count,
        'unpaid_sales_count': unpaid_sales_count,
        'total_expenses': total_expenses,
        'total_recipes': total_recipes,
        'net_result': net_result,
        'total_supplies': total_supplies,
        'supplies_count': supplies_count,
        'receivables_total': receivables_total,
        'supplier_debt_total': supplier_debt_total,
        'payments_received_total': payments_received_total,
        'supplier_payments_total': supplier_payments_total,
        'total_products': total_products,
        'in_stock_count': in_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'low_stock_count': low_stock_count,
        'stock_alert_count': stock_alert_count,
        'total_stock_units': total_stock_units,
        'categories_count': categories_count,
        'gammes_count': gammes_count,
        'rayons_count': rayons_count,
        'products_with_category_count': products_with_category_count,
        'products_with_gamme_count': products_with_gamme_count,
        'products_with_rayon_count': products_with_rayon_count,
        'clients_count': clients_count,
        'staff_count': staff_count,
        'suppliers_count': suppliers_count,
        'active_users_count': active_users_count,
        'inactive_users_count': inactive_users_count,
        'open_dailies_count': open_dailies_count,
        'inventory_sessions_count': inventory_sessions_count,
        'valid_inventory_units': valid_inventory_units,
        'invalid_inventory_units': invalid_inventory_units,
        'inventory_snapshot_count': inventory_snapshot_count,
        'today_revenue': today_revenue,
        'today_sales_count': today_sales_count,
        'today_products_sold': today_products_sold,
        'today_expenses': today_expenses,
        'today_recipes': today_recipes,
        'today_supplies_count': today_supplies_count,
        'today_supplies_total': today_supplies_total,
        'today_net': today_net,
        'invoice_total': invoice_total,
        'paid_invoices_count': paid_invoices_count,
        'sent_invoices_count': sent_invoices_count,
        'draft_invoices_count': draft_invoices_count,
        'cancelled_invoices_count': cancelled_invoices_count,
        'sales_paid_rate': to_percentage(paid_sales_count, sales_count),
        'sales_credit_rate': to_percentage(credit_sales_count, sales_count),
        'sales_unpaid_rate': to_percentage(unpaid_sales_count, sales_count),
        'stock_available_rate': to_percentage(in_stock_count, total_products),
        'stock_alert_rate': to_percentage(stock_alert_count, total_products),
        'stock_out_rate': to_percentage(out_of_stock_count, total_products),
        'invoice_paid_rate': to_percentage(paid_invoices_count, invoice_total),
        'invoice_sent_rate': to_percentage(sent_invoices_count, invoice_total),
        'invoice_draft_rate': to_percentage(draft_invoices_count, invoice_total),
        'invoice_cancelled_rate': to_percentage(cancelled_invoices_count, invoice_total),
        'recent_sales': recent_sales,
        'low_stock_products': low_stock_products,
        'top_products': top_products,
        'overdue_schedules': overdue_schedules,
    }
    return render(request, 'core/statistics.html', context)


@login_required
@module_required('dashboard')
def product_statistics(request):
    """Vue détaillée des statistiques produits avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return f"Du {start.strftime('%d/%m/%Y')} au {end.strftime('%d/%m/%Y')}"
        if start:
            return f"Depuis le {start.strftime('%d/%m/%Y')}"
        if end:
            return f"Jusqu'au {end.strftime('%d/%m/%Y')}"
        return "Toutes les données disponibles"

    def chart_bucket_for_range(start, end):
        if not start and not end:
            return TruncMonth('sale__create_at'), 'month'

        effective_end = end or timezone.localdate()
        effective_start = start or (effective_end - timedelta(days=180))
        span_days = max((effective_end - effective_start).days + 1, 1)

        if span_days <= 31:
            return TruncDate('sale__create_at'), 'day'
        if span_days <= 120:
            return TruncWeek('sale__create_at'), 'week'
        return TruncMonth('sale__create_at'), 'month'

    def format_bucket_label(bucket_value, bucket_kind):
        if hasattr(bucket_value, 'date'):
            bucket_date = timezone.localtime(bucket_value).date() if timezone.is_aware(bucket_value) else bucket_value.date()
        else:
            bucket_date = bucket_value

        if bucket_kind == 'month':
            return bucket_date.strftime('%b %Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '')
    gamme_id = request.GET.get('gamme', '')
    rayon_id = request.GET.get('rayon', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': ('7 derniers jours', 6),
        '30d': ('30 derniers jours', 29),
        '90d': ('90 derniers jours', 89),
        '365d': ('12 derniers mois', 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = 'Période personnalisée'
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    products_queryset = Product.objects.filter(
        delete_at__isnull=True,
    ).select_related('category', 'gamme', 'rayon')

    if search:
        products_queryset = products_queryset.filter(
            Q(name__icontains=search) | Q(code__icontains=search) | Q(brand__icontains=search)
        )
    if category_id:
        products_queryset = products_queryset.filter(category_id=category_id)
    if gamme_id:
        products_queryset = products_queryset.filter(gamme_id=gamme_id)
    if rayon_id:
        products_queryset = products_queryset.filter(rayon_id=rayon_id)

    product_ids = products_queryset.values('id')

    sales_queryset = SaleProduct.objects.filter(
        delete_at__isnull=True,
        sale__delete_at__isnull=True,
        product_id__in=product_ids,
    ).select_related('sale', 'product', 'product__category', 'product__gamme', 'product__rayon')

    supplies_queryset = Supply.objects.filter(
        delete_at__isnull=True,
        product_id__in=product_ids,
    ).select_related('product', 'supplier')

    if range_start:
        sales_queryset = sales_queryset.filter(sale__create_at__date__gte=range_start)
        supplies_queryset = supplies_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        sales_queryset = sales_queryset.filter(sale__create_at__date__lte=range_end)
        supplies_queryset = supplies_queryset.filter(create_at__date__lte=range_end)

    sales_queryset = sales_queryset.annotate(line_total=F('quantity') * F('unit_price'))

    total_products = products_queryset.count()
    total_stock_units = products_queryset.aggregate(total=Sum('stock'))['total'] or 0
    total_stock_value = products_queryset.annotate(
        stock_value=F('stock') * F('actual_price')
    ).aggregate(total=Sum('stock_value'))['total'] or 0

    total_revenue = sales_queryset.aggregate(total=Sum('line_total'))['total'] or 0
    total_units_sold = sales_queryset.aggregate(total=Sum('quantity'))['total'] or 0
    sales_count = sales_queryset.values('sale_id').distinct().count()
    average_sale_value = (total_revenue / sales_count) if sales_count else 0

    total_supplied_units = supplies_queryset.aggregate(total=Sum('quantity'))['total'] or 0
    total_supplies_amount = supplies_queryset.aggregate(total=Sum('total_price'))['total'] or 0

    out_of_stock_count = products_queryset.filter(stock=0).count()
    low_stock_count = products_queryset.filter(
        stock__gt=0,
        stock__lte=F('stock_limit'),
    ).exclude(stock_limit__isnull=True).count()
    healthy_stock_count = max(total_products - low_stock_count - out_of_stock_count, 0)
    stock_alert_count = low_stock_count + out_of_stock_count

    top_products = sales_queryset.values(
        'product_id',
        'product__code',
        'product__name',
        'product__category__name',
        'product__rayon__name',
        'product__gamme__name',
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('line_total'),
        sales_frequency=Count('sale_id', distinct=True),
    ).order_by('-total_revenue', '-total_quantity', 'product__name')[:8]

    low_stock_products = products_queryset.filter(
        Q(stock=0) | Q(stock__lte=F('stock_limit')),
    ).exclude(
        Q(stock__gt=0) & Q(stock_limit__isnull=True)
    ).order_by('stock', 'name')[:8]

    chart_bucket, bucket_kind = chart_bucket_for_range(range_start, range_end)
    sales_trend_rows = sales_queryset.annotate(
        bucket=chart_bucket,
    ).values('bucket').annotate(
        total_revenue=Sum('line_total'),
        total_quantity=Sum('quantity'),
    ).order_by('bucket')

    sales_trend_chart = {
        'labels': [format_bucket_label(row['bucket'], bucket_kind) for row in sales_trend_rows],
        'revenue': [float(row['total_revenue'] or 0) for row in sales_trend_rows],
        'quantity': [int(row['total_quantity'] or 0) for row in sales_trend_rows],
    }

    top_products_chart = {
        'labels': [row['product__name'] for row in top_products],
        'revenue': [float(row['total_revenue'] or 0) for row in top_products],
        'quantity': [int(row['total_quantity'] or 0) for row in top_products],
    }

    category_rows = list(
        products_queryset.values('category__name').annotate(
            product_count=Count('id'),
            stock_units=Sum('stock'),
        ).order_by('-product_count', '-stock_units', 'category__name')[:8]
    )
    category_chart = {
        'labels': [row['category__name'] or 'Sans catégorie' for row in category_rows],
        'counts': [int(row['product_count'] or 0) for row in category_rows],
        'stock': [int(row['stock_units'] or 0) for row in category_rows],
    }

    stock_health_chart = {
        'labels': ['Disponible', 'Stock bas', 'Rupture'],
        'values': [healthy_stock_count, low_stock_count, out_of_stock_count],
    }

    categories = Category.objects.filter(delete_at__isnull=True).order_by('name')
    gammes = Gamme.objects.filter(delete_at__isnull=True).order_by('name')
    rayons = Rayon.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Statistiques produits',
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'categories': categories,
        'gammes': gammes,
        'rayons': rayons,
        'current_period': period,
        'current_search': search,
        'current_category': category_id,
        'current_gamme': gamme_id,
        'current_rayon': rayon_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_products': total_products,
        'total_stock_units': total_stock_units,
        'total_stock_value': total_stock_value,
        'total_revenue': total_revenue,
        'total_units_sold': total_units_sold,
        'sales_count': sales_count,
        'average_sale_value': average_sale_value,
        'total_supplied_units': total_supplied_units,
        'total_supplies_amount': total_supplies_amount,
        'healthy_stock_count': healthy_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'stock_alert_count': stock_alert_count,
        'top_products': top_products,
        'low_stock_products': low_stock_products,
        'sales_trend_chart': sales_trend_chart,
        'top_products_chart': top_products_chart,
        'category_chart': category_chart,
        'stock_health_chart': stock_health_chart,
    }
    return render(request, 'core/statistics_products.html', context)


@login_required
@module_required('dashboard')
def sales_statistics(request):
    """Vue détaillée des statistiques ventes avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return f"Du {start.strftime('%d/%m/%Y')} au {end.strftime('%d/%m/%Y')}"
        if start:
            return f"Depuis le {start.strftime('%d/%m/%Y')}"
        if end:
            return f"Jusqu'au {end.strftime('%d/%m/%Y')}"
        return "Toutes les données disponibles"

    def chart_bucket_for_range(start, end):
        if not start and not end:
            return TruncMonth('create_at'), 'month'

        effective_end = end or timezone.localdate()
        effective_start = start or (effective_end - timedelta(days=180))
        span_days = max((effective_end - effective_start).days + 1, 1)

        if span_days <= 31:
            return TruncDate('create_at'), 'day'
        if span_days <= 120:
            return TruncWeek('create_at'), 'week'
        return TruncMonth('create_at'), 'month'

    def format_bucket_label(bucket_value, bucket_kind):
        if hasattr(bucket_value, 'date'):
            bucket_date = timezone.localtime(bucket_value).date() if timezone.is_aware(bucket_value) else bucket_value.date()
        else:
            bucket_date = bucket_value

        if bucket_kind == 'month':
            return bucket_date.strftime('%b %Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    def format_person_label(firstname, lastname, fallback):
        full_name = f"{firstname or ''} {lastname or ''}".strip()
        return full_name or fallback

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    client_id = request.GET.get('client', '')
    staff_id = request.GET.get('staff', '')
    sale_type = request.GET.get('type', '')
    payment_status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': ('7 derniers jours', 6),
        '30d': ('30 derniers jours', 29),
        '90d': ('90 derniers jours', 89),
        '365d': ('12 derniers mois', 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = 'Période personnalisée'
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    sales_queryset = Sale.objects.filter(
        delete_at__isnull=True,
    ).select_related('client', 'staff', 'daily')

    if search:
        sales_queryset = sales_queryset.filter(
            Q(client__firstname__icontains=search)
            | Q(client__lastname__icontains=search)
            | Q(staff__firstname__icontains=search)
            | Q(staff__lastname__icontains=search)
            | Q(id__icontains=search)
        )
    if client_id:
        sales_queryset = sales_queryset.filter(client_id=client_id)
    if staff_id:
        sales_queryset = sales_queryset.filter(staff_id=staff_id)
    if sale_type == 'cash':
        sales_queryset = sales_queryset.filter(is_credit=False)
    elif sale_type == 'credit':
        sales_queryset = sales_queryset.filter(is_credit=True)
    if payment_status == 'paid':
        sales_queryset = sales_queryset.filter(is_paid=True)
    elif payment_status == 'unpaid':
        sales_queryset = sales_queryset.filter(is_paid=False)
    if range_start:
        sales_queryset = sales_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        sales_queryset = sales_queryset.filter(create_at__date__lte=range_end)

    sale_ids = sales_queryset.values('id')
    sale_products_queryset = SaleProduct.objects.filter(
        delete_at__isnull=True,
        sale__delete_at__isnull=True,
        sale_id__in=sale_ids,
    )
    credit_sales_queryset = CreditSale.objects.filter(
        delete_at__isnull=True,
        sale__delete_at__isnull=True,
        sale_id__in=sale_ids,
    )

    total_revenue = sales_queryset.aggregate(total=Sum('total'))['total'] or 0
    sales_count = sales_queryset.count()
    products_sold_count = sale_products_queryset.aggregate(total=Sum('quantity'))['total'] or 0
    average_ticket = (total_revenue / sales_count) if sales_count else 0
    paid_sales_count = sales_queryset.filter(is_paid=True).count()
    unpaid_sales_count = sales_queryset.filter(is_paid=False).count()
    credit_sales_count = sales_queryset.filter(is_credit=True).count()
    cash_sales_count = max(sales_count - credit_sales_count, 0)
    paid_revenue = sales_queryset.filter(is_paid=True).aggregate(total=Sum('total'))['total'] or 0
    unpaid_revenue = sales_queryset.filter(is_paid=False).aggregate(total=Sum('total'))['total'] or 0
    outstanding_total = credit_sales_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    anonymous_sales_count = sales_queryset.filter(client__isnull=True).count()

    chart_bucket, bucket_kind = chart_bucket_for_range(range_start, range_end)
    sales_trend_rows = sales_queryset.annotate(
        bucket=chart_bucket,
    ).values('bucket').annotate(
        total_revenue=Sum('total'),
        total_sales=Count('id'),
    ).order_by('bucket')
    sales_trend_chart = {
        'labels': [format_bucket_label(row['bucket'], bucket_kind) for row in sales_trend_rows],
        'revenue': [float(row['total_revenue'] or 0) for row in sales_trend_rows],
        'sales': [int(row['total_sales'] or 0) for row in sales_trend_rows],
    }

    payment_status_chart = {
        'labels': ['Payées', 'Non payées'],
        'values': [paid_sales_count, unpaid_sales_count],
    }

    sale_type_chart = {
        'labels': ['Comptant', 'Crédit'],
        'values': [cash_sales_count, credit_sales_count],
    }

    staff_rows = list(
        sales_queryset.values(
            'staff_id',
            'staff__firstname',
            'staff__lastname',
        ).annotate(
            total_revenue=Sum('total'),
            total_sales=Count('id'),
        ).order_by('-total_revenue', '-total_sales')[:8]
    )
    staff_performance_chart = {
        'labels': [
            format_person_label(row['staff__firstname'], row['staff__lastname'], 'Non assigné')
            for row in staff_rows
        ],
        'revenue': [float(row['total_revenue'] or 0) for row in staff_rows],
        'sales': [int(row['total_sales'] or 0) for row in staff_rows],
    }

    top_client_rows = list(
        sales_queryset.values(
            'client_id',
            'client__firstname',
            'client__lastname',
        ).annotate(
            total_revenue=Sum('total'),
            total_sales=Count('id'),
        ).order_by('-total_revenue', '-total_sales')[:8]
    )
    top_clients = [
        {
            'label': format_person_label(row['client__firstname'], row['client__lastname'], 'Client comptoir'),
            'total_revenue': row['total_revenue'] or 0,
            'total_sales': row['total_sales'] or 0,
        }
        for row in top_client_rows
    ]

    recent_sales = sales_queryset.order_by('-create_at')[:8]
    clients = Client.objects.filter(delete_at__isnull=True).order_by('firstname', 'lastname')
    staff_members = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).order_by('firstname', 'lastname')

    context = {
        'page_title': 'Statistiques ventes',
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'clients': clients,
        'staff_members': staff_members,
        'current_period': period,
        'current_search': search,
        'current_client': client_id,
        'current_staff': staff_id,
        'current_type': sale_type,
        'current_status': payment_status,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'sales_count': sales_count,
        'total_revenue': total_revenue,
        'products_sold_count': products_sold_count,
        'average_ticket': average_ticket,
        'paid_sales_count': paid_sales_count,
        'unpaid_sales_count': unpaid_sales_count,
        'credit_sales_count': credit_sales_count,
        'cash_sales_count': cash_sales_count,
        'paid_revenue': paid_revenue,
        'unpaid_revenue': unpaid_revenue,
        'outstanding_total': outstanding_total,
        'anonymous_sales_count': anonymous_sales_count,
        'top_clients': top_clients,
        'recent_sales': recent_sales,
        'sales_trend_chart': sales_trend_chart,
        'payment_status_chart': payment_status_chart,
        'sale_type_chart': sale_type_chart,
        'staff_performance_chart': staff_performance_chart,
    }
    return render(request, 'core/statistics_sales.html', context)


@login_required
@module_required('dashboard')
def personnel_statistics(request):
    """Vue détaillée des statistiques personnel avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings, AppModule

    def format_period_label(start, end):
        if start and end:
            return f"Du {start.strftime('%d/%m/%Y')} au {end.strftime('%d/%m/%Y')}"
        if start:
            return f"Depuis le {start.strftime('%d/%m/%Y')}"
        if end:
            return f"Jusqu'au {end.strftime('%d/%m/%Y')}"
        return "Toutes les données disponibles"

    def chart_bucket_for_range(field_name, start, end):
        if not start and not end:
            return TruncMonth(field_name), 'month'

        effective_end = end or timezone.localdate()
        effective_start = start or (effective_end - timedelta(days=180))
        span_days = max((effective_end - effective_start).days + 1, 1)

        if span_days <= 31:
            return TruncDate(field_name), 'day'
        if span_days <= 120:
            return TruncWeek(field_name), 'week'
        return TruncMonth(field_name), 'month'

    def format_bucket_label(bucket_value, bucket_kind):
        if hasattr(bucket_value, 'date'):
            bucket_date = timezone.localtime(bucket_value).date() if timezone.is_aware(bucket_value) else bucket_value.date()
        else:
            bucket_date = bucket_value

        if bucket_kind == 'month':
            return bucket_date.strftime('%b %Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    def format_person_label(firstname, lastname, username):
        full_name = f"{firstname or ''} {lastname or ''}".strip()
        return full_name or username or 'Utilisateur'

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '')
    role = request.GET.get('role', '').strip()
    gender = request.GET.get('gender', '').strip()
    module_code = request.GET.get('module', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': ('7 derniers jours', 6),
        '30d': ('30 derniers jours', 29),
        '90d': ('90 derniers jours', 89),
        '365d': ('12 derniers mois', 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = 'Période personnalisée'
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    base_staff_queryset = CustomUser.objects.filter(
        delete_at__isnull=True,
    ).prefetch_related('allowed_modules')

    roles = list(
        base_staff_queryset.exclude(role__isnull=True).exclude(role='').values_list('role', flat=True).distinct().order_by('role')
    )
    genders = list(
        base_staff_queryset.exclude(gender__isnull=True).exclude(gender='').values_list('gender', flat=True).distinct().order_by('gender')
    )
    modules = AppModule.objects.filter(is_active=True).order_by('order', 'name')

    staff_queryset = base_staff_queryset
    if search:
        staff_queryset = staff_queryset.filter(
            Q(username__icontains=search)
            | Q(firstname__icontains=search)
            | Q(lastname__icontains=search)
            | Q(email__icontains=search)
            | Q(phone_number__icontains=search)
        )
    if status == 'active':
        staff_queryset = staff_queryset.filter(is_active=True)
    elif status == 'inactive':
        staff_queryset = staff_queryset.filter(is_active=False)
    elif status == 'superuser':
        staff_queryset = staff_queryset.filter(is_superuser=True)
    if role:
        staff_queryset = staff_queryset.filter(role=role)
    if gender:
        staff_queryset = staff_queryset.filter(gender=gender)
    if module_code:
        staff_queryset = staff_queryset.filter(allowed_modules__code=module_code, allowed_modules__is_active=True)

    staff_queryset = staff_queryset.distinct()
    staff_ids = list(staff_queryset.values_list('id', flat=True))

    if staff_ids:
        sales_queryset = Sale.objects.filter(delete_at__isnull=True, staff_id__in=staff_ids)
        supplies_queryset = Supply.objects.filter(delete_at__isnull=True, staff_id__in=staff_ids)
        inventories_queryset = Inventory.objects.filter(delete_at__isnull=True, staff_id__in=staff_ids)
        daily_inventories_queryset = DailyInventory.objects.filter(delete_at__isnull=True, staff_id__in=staff_ids)
    else:
        sales_queryset = Sale.objects.none()
        supplies_queryset = Supply.objects.none()
        inventories_queryset = Inventory.objects.none()
        daily_inventories_queryset = DailyInventory.objects.none()

    if range_start:
        sales_queryset = sales_queryset.filter(create_at__date__gte=range_start)
        supplies_queryset = supplies_queryset.filter(create_at__date__gte=range_start)
        inventories_queryset = inventories_queryset.filter(create_at__date__gte=range_start)
        daily_inventories_queryset = daily_inventories_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        sales_queryset = sales_queryset.filter(create_at__date__lte=range_end)
        supplies_queryset = supplies_queryset.filter(create_at__date__lte=range_end)
        inventories_queryset = inventories_queryset.filter(create_at__date__lte=range_end)
        daily_inventories_queryset = daily_inventories_queryset.filter(create_at__date__lte=range_end)

    total_staff = staff_queryset.count()
    active_staff_count = staff_queryset.filter(is_active=True).count()
    inactive_staff_count = staff_queryset.filter(is_active=False).count()
    admin_staff_count = staff_queryset.filter(is_superuser=True).count()
    distinct_roles_count = staff_queryset.exclude(role__isnull=True).exclude(role='').values('role').distinct().count()
    staff_with_modules_count = staff_queryset.filter(allowed_modules__is_active=True).distinct().count()

    joined_staff_queryset = staff_queryset
    if range_start:
        joined_staff_queryset = joined_staff_queryset.filter(date_joined__date__gte=range_start)
    if range_end:
        joined_staff_queryset = joined_staff_queryset.filter(date_joined__date__lte=range_end)
    joined_staff_count = joined_staff_queryset.count()

    sales_count = sales_queryset.count()
    total_revenue = sales_queryset.aggregate(total=Sum('total'))['total'] or 0
    supplies_count = supplies_queryset.count()
    inventory_sessions_count = inventories_queryset.count()
    daily_inventory_count = daily_inventories_queryset.count()
    stock_actions_count = supplies_count + inventory_sessions_count + daily_inventory_count

    active_contributor_ids = set(sales_queryset.exclude(staff_id__isnull=True).values_list('staff_id', flat=True))
    active_contributor_ids.update(supplies_queryset.exclude(staff_id__isnull=True).values_list('staff_id', flat=True))
    active_contributor_ids.update(inventories_queryset.exclude(staff_id__isnull=True).values_list('staff_id', flat=True))
    active_contributor_ids.update(daily_inventories_queryset.exclude(staff_id__isnull=True).values_list('staff_id', flat=True))
    active_contributors_count = len(active_contributor_ids)
    contributor_rate = round((active_contributors_count / total_staff) * 100, 1) if total_staff else 0

    status_distribution_chart = {
        'labels': ['Actifs', 'Inactifs'],
        'values': [active_staff_count, inactive_staff_count],
    }

    role_rows = list(
        staff_queryset.values('role').annotate(total_users=Count('id')).order_by('-total_users', 'role')[:8]
    )
    role_distribution_chart = {
        'labels': [row['role'] or 'Non renseigné' for row in role_rows],
        'values': [int(row['total_users'] or 0) for row in role_rows],
    }

    sales_bucket, bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    supplies_bucket, _ = chart_bucket_for_range('create_at', range_start, range_end)
    inventories_bucket, _ = chart_bucket_for_range('create_at', range_start, range_end)
    daily_bucket, _ = chart_bucket_for_range('create_at', range_start, range_end)

    sales_trend_rows = list(
        sales_queryset.annotate(bucket=sales_bucket).values('bucket').annotate(total_sales=Count('id')).order_by('bucket')
    )
    supplies_trend_rows = list(
        supplies_queryset.annotate(bucket=supplies_bucket).values('bucket').annotate(total_supplies=Count('id')).order_by('bucket')
    )
    inventories_trend_rows = list(
        inventories_queryset.annotate(bucket=inventories_bucket).values('bucket').annotate(total_inventories=Count('id')).order_by('bucket')
    )
    daily_trend_rows = list(
        daily_inventories_queryset.annotate(bucket=daily_bucket).values('bucket').annotate(total_daily=Count('id')).order_by('bucket')
    )

    sales_trend_map = {row['bucket']: int(row['total_sales'] or 0) for row in sales_trend_rows if row['bucket'] is not None}
    supplies_trend_map = {row['bucket']: int(row['total_supplies'] or 0) for row in supplies_trend_rows if row['bucket'] is not None}
    inventories_trend_map = {row['bucket']: int(row['total_inventories'] or 0) for row in inventories_trend_rows if row['bucket'] is not None}
    daily_trend_map = {row['bucket']: int(row['total_daily'] or 0) for row in daily_trend_rows if row['bucket'] is not None}
    trend_buckets = sorted(
        set(sales_trend_map.keys())
        | set(supplies_trend_map.keys())
        | set(inventories_trend_map.keys())
        | set(daily_trend_map.keys())
    )
    activity_trend_chart = {
        'labels': [format_bucket_label(bucket, bucket_kind) for bucket in trend_buckets],
        'sales': [sales_trend_map.get(bucket, 0) for bucket in trend_buckets],
        'supplies': [supplies_trend_map.get(bucket, 0) for bucket in trend_buckets],
        'stock_actions': [inventories_trend_map.get(bucket, 0) + daily_trend_map.get(bucket, 0) for bucket in trend_buckets],
    }

    sales_activity_rows = list(
        sales_queryset.exclude(staff_id__isnull=True).values(
            'staff_id',
            'staff__firstname',
            'staff__lastname',
            'staff__username',
        ).annotate(
            total_revenue=Sum('total'),
            total_sales=Count('id'),
        ).order_by('-total_revenue', '-total_sales')
    )
    supplies_activity_rows = list(
        supplies_queryset.exclude(staff_id__isnull=True).values('staff_id').annotate(total_supplies=Count('id'))
    )
    inventories_activity_rows = list(
        inventories_queryset.exclude(staff_id__isnull=True).values('staff_id').annotate(total_inventories=Count('id'))
    )
    daily_activity_rows = list(
        daily_inventories_queryset.exclude(staff_id__isnull=True).values('staff_id').annotate(total_daily=Count('id'))
    )

    sales_activity_map = {
        row['staff_id']: {
            'label': format_person_label(row['staff__firstname'], row['staff__lastname'], row['staff__username']),
            'total_revenue': float(row['total_revenue'] or 0),
            'sales_count': int(row['total_sales'] or 0),
        }
        for row in sales_activity_rows
    }
    supplies_activity_map = {row['staff_id']: int(row['total_supplies'] or 0) for row in supplies_activity_rows}
    inventories_activity_map = {row['staff_id']: int(row['total_inventories'] or 0) for row in inventories_activity_rows}
    daily_activity_map = {row['staff_id']: int(row['total_daily'] or 0) for row in daily_activity_rows}

    top_staff = []
    for member in staff_queryset.order_by('firstname', 'lastname', 'username'):
        active_modules = [module.name for module in member.allowed_modules.all() if module.is_active]
        sales_data = sales_activity_map.get(member.id, {})
        supply_count = supplies_activity_map.get(member.id, 0)
        stock_count = inventories_activity_map.get(member.id, 0) + daily_activity_map.get(member.id, 0)
        sales_total = int(sales_data.get('sales_count', 0))
        total_actions = sales_total + supply_count + stock_count
        top_staff.append({
            'label': sales_data.get('label') or member.get_full_name() or member.username,
            'username': member.username,
            'role': member.role or 'Non renseigné',
            'status_label': 'Actif' if member.is_active else 'Inactif',
            'sales_count': sales_total,
            'supply_count': supply_count,
            'stock_actions': stock_count,
            'total_actions': total_actions,
            'total_revenue': sales_data.get('total_revenue', 0),
            'module_count': len(active_modules),
            'modules_label': ', '.join(active_modules) or 'Aucun module',
        })

    top_staff = sorted(
        top_staff,
        key=lambda row: (row['total_actions'], row['total_revenue'], row['sales_count']),
        reverse=True,
    )[:8]
    top_contributors_chart = {
        'labels': [row['label'] for row in top_staff],
        'sales': [row['sales_count'] for row in top_staff],
        'supplies': [row['supply_count'] for row in top_staff],
        'stock_actions': [row['stock_actions'] for row in top_staff],
    }

    recent_staff = []
    for member in staff_queryset.order_by('-date_joined', '-id')[:8]:
        active_modules = [module.name for module in member.allowed_modules.all() if module.is_active]
        recent_staff.append({
            'label': member.get_full_name() or member.username,
            'username': member.username,
            'role': member.role or 'Non renseigné',
            'gender': member.gender or 'Non renseigné',
            'status_label': 'Actif' if member.is_active else 'Inactif',
            'status_class': 'success' if member.is_active else 'warning',
            'modules_label': ', '.join(active_modules) or 'Aucun module',
            'date_joined': member.date_joined,
        })

    context = {
        'page_title': 'Statistiques personnel',
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'roles': roles,
        'genders': genders,
        'modules': modules,
        'current_period': period,
        'current_search': search,
        'current_status': status,
        'current_role': role,
        'current_gender': gender,
        'current_module': module_code,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_staff': total_staff,
        'active_staff_count': active_staff_count,
        'inactive_staff_count': inactive_staff_count,
        'admin_staff_count': admin_staff_count,
        'distinct_roles_count': distinct_roles_count,
        'staff_with_modules_count': staff_with_modules_count,
        'joined_staff_count': joined_staff_count,
        'active_contributors_count': active_contributors_count,
        'contributor_rate': contributor_rate,
        'sales_count': sales_count,
        'total_revenue': total_revenue,
        'supplies_count': supplies_count,
        'inventory_sessions_count': inventory_sessions_count,
        'daily_inventory_count': daily_inventory_count,
        'stock_actions_count': stock_actions_count,
        'status_distribution_chart': status_distribution_chart,
        'role_distribution_chart': role_distribution_chart,
        'activity_trend_chart': activity_trend_chart,
        'top_contributors_chart': top_contributors_chart,
        'top_staff': top_staff,
        'recent_staff': recent_staff,
    }
    return render(request, 'core/statistics_personnel.html', context)


@login_required
@module_required('sales')
def sales(request):
    """Vue de la page des ventes"""
    from django.db.models import Sum, F
    
    view_mode = request.GET.get('view_mode', 'sales')  # 'sales' or 'products'
    search = request.GET.get('search', '').strip()
    
    # Récupérer le Daily actif (non fermé)
    # current_daily = Daily.objects.filter(end_date__isnull=True).order_by('-start_date').first()
    current_daily = DailyService().get_or_create_active_daily()

    if current_daily:
        if view_mode == 'products':
            # Mode produits vendus : afficher SaleProduct directement pour le daily en cours
            queryset = SaleProduct.objects.filter(
                delete_at__isnull=True,
                sale__daily=current_daily,
            ).select_related('sale', 'sale__client', 'sale__staff', 'product', 'product__category')
            
            # Filtre recherche (produit, client, vendeur, ID vente)
            if search:
                queryset = queryset.filter(
                    Q(product__name__icontains=search)
                    | Q(sale__client__firstname__icontains=search)
                    | Q(sale__client__lastname__icontains=search)
                    | Q(sale__staff__firstname__icontains=search)
                    | Q(sale__staff__lastname__icontains=search)
                    | Q(sale__id__icontains=search)
                )
            
            queryset = queryset.order_by('-sale__create_at')
            
            # Total des produits vendus (quantité * prix unitaire)
            from django.db.models import Sum as DbSum
            total_revenue = queryset.annotate(
                line_total=F('quantity') * F('unit_price')
            ).aggregate(total=DbSum('line_total'))['total'] or 0
            
            sale_products_list = queryset
            sales_list = []
        else:
            # Mode ventes par défaut
            sales_list = Sale.objects.select_related('client', 'staff', 'daily', 'credit_info').filter(
                delete_at__isnull=True,
                daily=current_daily
            ).order_by('-create_at')
            
            # Filtre recherche (client, vendeur, montant, ID)
            if search:
                sales_list = sales_list.filter(
                    Q(client__firstname__icontains=search)
                    | Q(client__lastname__icontains=search)
                    | Q(staff__firstname__icontains=search)
                    | Q(staff__lastname__icontains=search)
                    | Q(id__icontains=search)
                )
            
            # Calculer la recette totale du jour
            total_revenue = sales_list.aggregate(total=Sum('total'))['total'] or 0
            sale_products_list = []
    else:
        # Aucun Daily actif
        sales_list = Sale.objects.none()
        sale_products_list = []
        total_revenue = 0

    # Récupérer tous les clients actifs
    clients_list = Client.objects.filter(delete_at__isnull=True).order_by('firstname')

    context = {
        'page_title': 'Ventes',
        'sales': sales_list,
        'sale_products': sale_products_list,
        'clients': clients_list,
        'current_daily': current_daily,
        'total_revenue': total_revenue,
        'view_mode': view_mode,
        'current_search': search,
    }
    return render(request, 'core/sales.html', context)


@login_required
@module_required('sales')
def sales_history(request):
    """Vue de l'historique complet des ventes avec filtres et pagination"""
    from django.db.models import Sum, F

    search = request.GET.get('search', '').strip()
    client_id = request.GET.get('client', '')
    staff_id = request.GET.get('staff', '')
    sale_type = request.GET.get('type', '')
    payment_status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    view_mode = request.GET.get('view_mode', 'sales')  # 'sales' or 'products'

    if view_mode == 'products':
        # Mode produits vendus : afficher SaleProduct directement
        queryset = SaleProduct.objects.filter(
            delete_at__isnull=True,
        ).select_related('sale', 'sale__client', 'sale__staff', 'product', 'product__category')

        # Filtre recherche (produit, client, vendeur, ID vente)
        if search:
            queryset = queryset.filter(
                Q(product__name__icontains=search)
                | Q(sale__client__firstname__icontains=search)
                | Q(sale__client__lastname__icontains=search)
                | Q(sale__staff__firstname__icontains=search)
                | Q(sale__staff__lastname__icontains=search)
                | Q(sale__id__icontains=search)
            )

        # Filtre client
        if client_id:
            queryset = queryset.filter(sale__client_id=client_id)

        # Filtre vendeur
        if staff_id:
            queryset = queryset.filter(sale__staff_id=staff_id)

        # Filtre type (comptant / crédit)
        if sale_type == 'cash':
            queryset = queryset.filter(sale__is_credit=False)
        elif sale_type == 'credit':
            queryset = queryset.filter(sale__is_credit=True)

        # Filtre statut paiement
        if payment_status == 'paid':
            queryset = queryset.filter(sale__is_paid=True)
        elif payment_status == 'unpaid':
            queryset = queryset.filter(sale__is_paid=False)

        # Filtre dates
        if date_from:
            queryset = queryset.filter(sale__create_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(sale__create_at__date__lte=date_to)

        queryset = queryset.order_by('-sale__create_at')

        # Total des produits vendus (quantité * prix unitaire)
        from django.db.models import Sum as DbSum
        total_products_amount = queryset.annotate(
            line_total=F('quantity') * F('unit_price')
        ).aggregate(total=DbSum('line_total'))['total'] or 0

        paginator = Paginator(queryset, 20)
        page_obj = paginator.get_page(page_number)

        # Listes pour les dropdowns
        clients_list = Client.objects.filter(delete_at__isnull=True).order_by('firstname')
        staff_list = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).order_by('firstname')

        context = {
            'page_title': 'Historique des ventes - Produits',
            'page_obj': page_obj,
            'sale_products': page_obj.object_list,
            'view_mode': 'products',
            'clients': clients_list,
            'staff_members': staff_list,
            'current_search': search,
            'current_client': client_id,
            'current_staff': staff_id,
            'current_type': sale_type,
            'current_status': payment_status,
            'current_date_from': date_from,
            'current_date_to': date_to,
            'total_count': paginator.count,
            'total_sales_amount': total_products_amount,
        }
        return render(request, 'core/sales_history.html', context)

    # Mode ventes par défaut (existing code)
    queryset = Sale.objects.filter(
        delete_at__isnull=True,
    ).select_related('client', 'staff', 'daily', 'credit_info')

    # Filtre recherche (client, vendeur, montant, ID)
    if search:
        queryset = queryset.filter(
            Q(client__firstname__icontains=search)
            | Q(client__lastname__icontains=search)
            | Q(staff__firstname__icontains=search)
            | Q(staff__lastname__icontains=search)
            | Q(id__icontains=search)
        )

    # Filtre client
    if client_id:
        queryset = queryset.filter(client_id=client_id)

    # Filtre vendeur
    if staff_id:
        queryset = queryset.filter(staff_id=staff_id)

    # Filtre type (comptant / crédit)
    if sale_type == 'cash':
        queryset = queryset.filter(is_credit=False)
    elif sale_type == 'credit':
        queryset = queryset.filter(is_credit=True)

    # Filtre statut paiement
    if payment_status == 'paid':
        queryset = queryset.filter(is_paid=True)
    elif payment_status == 'unpaid':
        queryset = queryset.filter(is_paid=False)

    # Filtre dates
    if date_from:
        queryset = queryset.filter(create_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(create_at__date__lte=date_to)

    queryset = queryset.order_by('-create_at')

    # Total des ventes filtrées
    total_sales_amount = queryset.aggregate(total=Sum('total'))['total'] or 0

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    # Listes pour les dropdowns
    clients_list = Client.objects.filter(delete_at__isnull=True).order_by('firstname')
    staff_list = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).order_by('firstname')

    context = {
        'page_title': 'Historique des ventes',
        'page_obj': page_obj,
        'sales': page_obj.object_list,
        'view_mode': 'sales',
        'clients': clients_list,
        'staff_members': staff_list,
        'current_search': search,
        'current_client': client_id,
        'current_staff': staff_id,
        'current_type': sale_type,
        'current_status': payment_status,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_count': paginator.count,
        'total_sales_amount': total_sales_amount,
    }
    return render(request, 'core/sales_history.html', context)


@login_required
@module_required('products')
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
@module_required('products')
def product_detail(request, pk):
    """Vue détaillée d'un produit."""
    product = get_object_or_404(
        Product.objects.filter(delete_at__isnull=True).select_related(
            'category', 'gamme', 'rayon', 'grammage_type'
        ),
        pk=pk,
    )

    product_images = list(
        product.images.filter(delete_at__isnull=True).order_by('-is_primary', 'id')
    )
    primary_image = product_images[0] if product_images else None

    context = {
        'page_title': product.name,
        'product': product,
        'product_images': product_images,
        'primary_image': primary_image,
    }
    return render(request, 'core/product_detail.html', context)


INVENTORY_PER_PAGE_CHOICES = [10, 25, 50, 100]


@login_required
@module_required('inventory')
def inventory(request):
    """Vue de la page de l'inventaire avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    staff_id = request.GET.get('staff', '')
    exercise_id = request.GET.get('exercise', '')
    if not exercise_id and 'exercise' not in request.GET:
        # Par défaut, sélectionner l'exercice en cours
        current_ex = ExerciseService.get_or_create_current_exercise()
        exercise_id = str(current_ex.id)
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)

    # Nombre d'éléments par page (10, 25, 50, 100)
    try:
        per_page = int(request.GET.get('per_page', 25))
    except (ValueError, TypeError):
        per_page = 25
    if per_page not in INVENTORY_PER_PAGE_CHOICES:
        per_page = 25

    queryset = Inventory.objects.filter(
        delete_at__isnull=True,
    ).select_related('product', 'staff', 'exercise')

    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search) | Q(product__code__icontains=search)
        )
    if staff_id:
        queryset = queryset.filter(staff_id=staff_id)
    if exercise_id:
        queryset = queryset.filter(exercise_id=exercise_id)
    if date_from:
        queryset = queryset.filter(create_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(create_at__date__lte=date_to)

    queryset = queryset.order_by('-create_at')

    total_valid = queryset.aggregate(total=Sum('valid_product_count'))['total'] or 0
    total_invalid = queryset.aggregate(total=Sum('invalid_product_count'))['total'] or 0

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)

    staff_list = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).order_by('firstname')
    exercises = Exercise.objects.filter(delete_at__isnull=True).order_by('-start_date')

    context = {
        'page_title': 'Inventaire',
        'page_obj': page_obj,
        'inventories': page_obj.object_list,
        'staff_members': staff_list,
        'exercises': exercises,
        'current_search': search,
        'current_staff': staff_id,
        'current_exercise': exercise_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'current_per_page': per_page,
        'per_page_choices': INVENTORY_PER_PAGE_CHOICES,
        'total_count': paginator.count,
        'total_valid': total_valid,
        'total_invalid': total_invalid,
    }
    return render(request, 'core/inventory.html', context)


@login_required
@module_required('inventory')
def add_inventory(request):
    """Vue pour ajouter un nouvel enregistrement d'inventaire"""
    if request.method == 'POST':
        form = InventoryForm(request.POST)
        if form.is_valid():
            inventory_record = form.save(commit=False)
            inventory_record.staff = request.user
            inventory_record.exercise = ExerciseService.get_or_create_current_exercise()
            if inventory_record.invalid_product_count is None:
                inventory_record.invalid_product_count = 0
            inventory_record.save()

            messages.success(
                request,
                f'Inventaire pour "{inventory_record.product.name}" enregistré avec succès '
                f'({inventory_record.valid_product_count} valides, {inventory_record.invalid_product_count} invalides).'
            )
            return redirect('inventory')
    else:
        form = InventoryForm()

    context = {
        'page_title': 'Nouvel enregistrement d\'inventaire',
        'form': form,
    }
    return render(request, 'core/inventory_add.html', context)


@login_required
@module_required('inventory')
def close_inventory_summary(request):
    """Vue résumé et liste des produits pour la clôture de l'inventaire de l'exercice courant"""
    current_exercise = ExerciseService.get_or_create_current_exercise()

    # Inventaires non clôturés pour l'exercice courant
    inventories_qs = Inventory.objects.filter(
        exercise=current_exercise,
        delete_at__isnull=True,
        is_close=False,
    )

    # Statistiques agrégées
    stats = inventories_qs.aggregate(
        total_valid=Sum('valid_product_count'),
        total_invalid=Sum('invalid_product_count'),
    )
    total_valid = stats['total_valid'] or 0
    total_invalid = stats['total_invalid'] or 0
    total_records = inventories_qs.count()

    # Agrégation par produit
    products_data = inventories_qs.values(
        'product__id', 'product__name', 'product__code', 'product__stock'
    ).annotate(
        total_valid=Sum('valid_product_count'),
        total_invalid=Sum('invalid_product_count'),
    ).order_by('product__name')

    products_list = []
    for p in products_data:
        p['total_count'] = (p['total_valid'] or 0) + (p['total_invalid'] or 0)
        p['stock_difference'] = (p['total_valid'] or 0) - (p['product__stock'] or 0)
        products_list.append(p)

    context = {
        'page_title': 'Clôturer l\'inventaire',
        'exercise': current_exercise,
        'total_valid': total_valid,
        'total_invalid': total_invalid,
        'total_count': total_valid + total_invalid,
        'total_records': total_records,
        'total_products': len(products_list),
        'products': products_list,
    }
    return render(request, 'core/inventory_close_summary.html', context)


@login_required
@module_required('inventory')
@require_POST
def close_inventory_confirm(request):
    """Action de clôture : met à jour le stock et marque les inventaires comme clôturés"""
    current_exercise = ExerciseService.get_or_create_current_exercise()

    # Inventaires non clôturés pour l'exercice courant
    inventories_qs = Inventory.objects.filter(
        exercise=current_exercise,
        delete_at__isnull=True,
        is_close=False,
    )

    if not inventories_qs.exists():
        messages.error(request, 'Aucun inventaire à clôturer pour l\'exercice courant.')
        return redirect('inventory')

    with transaction.atomic():
        # Agrégation par produit (valid + invalid)
        products_data = inventories_qs.values('product__id').annotate(
            total_valid=Sum('valid_product_count'),
            total_invalid=Sum('invalid_product_count'),
        )

        # Créer les snapshots et mettre à jour le stock
        updated_count = 0
        for item in products_data:
            product = Product.objects.select_for_update().get(id=item['product__id'])
            total_valid = item['total_valid'] or 0
            total_invalid = item['total_invalid'] or 0

            # Créer le snapshot avant de modifier le stock
            InventorySnapshot.objects.create(
                product=product,
                exercise=current_exercise,
                stock_before=product.stock or 0,
                total_counted=total_valid + total_invalid,
                total_valid=total_valid,
                total_invalid=total_invalid,
                stock_after=total_valid,
                selling_price=product.actual_price,
                purchase_price=product.last_purchase_price,
            )

            # Mettre à jour le stock avec la quantité valide cumulée
            product.stock = total_valid
            product.save(update_fields=['stock'])
            updated_count += 1

        # Marquer tous les inventaires comme clôturés
        inventories_qs.update(is_close=True)

        # Fermer l'exercice courant
        current_exercise.end_date = timezone.now()
        current_exercise.save(update_fields=['end_date'])

    messages.success(
        request,
        f'Inventaire clôturé avec succès. Stock mis à jour pour {updated_count} produit(s). L\'exercice a été fermé.'
    )
    return redirect('inventory')


SNAPSHOT_PER_PAGE_CHOICES = [10, 25, 50, 100]


@login_required
@module_required('inventory')
def inventory_history(request):
    """Vue de l'historique des inventaires clôturés (InventorySnapshot)"""
    search = request.GET.get('search', '').strip()
    exercise_id = request.GET.get('exercise', '')
    if not exercise_id and 'exercise' not in request.GET:
        # Par défaut, sélectionner le dernier exercice (le plus récent)
        last_exercise = Exercise.objects.filter(
            delete_at__isnull=True,
        ).order_by('-start_date').first()
        if last_exercise:
            exercise_id = str(last_exercise.id)
    page_number = request.GET.get('page', 1)

    try:
        per_page = int(request.GET.get('per_page', 25))
    except (ValueError, TypeError):
        per_page = 25
    if per_page not in SNAPSHOT_PER_PAGE_CHOICES:
        per_page = 25

    queryset = InventorySnapshot.objects.filter(
        delete_at__isnull=True,
    ).select_related('product', 'exercise')

    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search) | Q(product__code__icontains=search)
        )
    if exercise_id:
        queryset = queryset.filter(exercise_id=exercise_id)

    queryset = queryset.order_by('-create_at')

    # Totaux agrégés
    totals = queryset.aggregate(
        sum_stock_before=Sum('stock_before'),
        sum_total_valid=Sum('total_valid'),
        sum_total_invalid=Sum('total_invalid'),
        sum_stock_after=Sum('stock_after'),
    )

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)

    exercises = Exercise.objects.filter(delete_at__isnull=True).order_by('-start_date')

    context = {
        'page_title': 'Historique des inventaires',
        'page_obj': page_obj,
        'snapshots': page_obj.object_list,
        'exercises': exercises,
        'current_search': search,
        'current_exercise': exercise_id,
        'current_per_page': per_page,
        'per_page_choices': SNAPSHOT_PER_PAGE_CHOICES,
        'total_count': paginator.count,
        'sum_stock_before': totals['sum_stock_before'] or 0,
        'sum_total_valid': totals['sum_total_valid'] or 0,
        'sum_total_invalid': totals['sum_total_invalid'] or 0,
        'sum_stock_after': totals['sum_stock_after'] or 0,
    }
    return render(request, 'core/inventory_history.html', context)


@login_required
@module_required('contacts')
def contacts(request):
    """Vue combinée : Clients et Personnel avec sous-onglets"""
    tab = request.GET.get('tab', 'clients')
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    if tab == 'staff':
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
        'page_title': 'Utilisateurs',
        'current_tab': tab,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/contacts.html', context)


@login_required
@module_required('suppliers')
def suppliers_list(request):
    """Vue de la page Fournisseurs dédiée avec liste, recherche, pagination"""
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    queryset = Supplier.objects.filter(delete_at__isnull=True)
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(contact_phone__icontains=search) | Q(niu__icontains=search)
        )
    queryset = queryset.order_by('name')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Fournisseurs',
        'current_search': search,
        'page_obj': page_obj,
        'suppliers': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/suppliers.html', context)


@login_required
@module_required('contacts')
def add_client(request):
    """Vue pour ajouter un nouveau client"""
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Client "{form.cleaned_data["firstname"]}" créé avec succès.')
            return redirect('contacts')
    else:
        form = ClientForm()

    context = {
        'page_title': 'Nouveau client',
        'form': form,
        'form_title': 'Nouveau client',
        'form_subtitle': 'Créer un nouveau client',
        'back_url': 'contacts',
        'back_tab': 'clients',
    }
    return render(request, 'core/contacts_form.html', context)


@login_required
@module_required('contacts')
def edit_client(request, pk):
    """Vue pour modifier un client"""
    client = get_object_or_404(Client, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, f'Client "{client.get_full_name()}" modifié avec succès.')
            return redirect('contacts')
    else:
        form = ClientForm(instance=client)

    context = {
        'page_title': f'Modifier {client.get_full_name()}',
        'form': form,
        'form_title': 'Modifier le client',
        'form_subtitle': f'Modifier les informations de {client.get_full_name()}',
        'back_url': 'contacts',
        'back_tab': 'clients',
    }
    return render(request, 'core/contacts_form.html', context)


@login_required
@module_required('suppliers')
def add_supplier(request):
    """Vue pour ajouter un nouveau fournisseur"""
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Fournisseur "{form.cleaned_data["name"]}" créé avec succès.')
            return redirect('suppliers')
    else:
        form = SupplierForm()

    context = {
        'page_title': 'Nouveau fournisseur',
        'form': form,
        'form_title': 'Nouveau fournisseur',
        'form_subtitle': 'Créer un nouveau fournisseur',
        'back_url': 'suppliers',
    }
    return render(request, 'core/supplier_form.html', context)


@login_required
@module_required('suppliers')
def edit_supplier(request, pk):
    """Vue pour modifier un fournisseur"""
    supplier = get_object_or_404(Supplier, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f'Fournisseur "{supplier.name}" modifié avec succès.')
            return redirect('suppliers')
    else:
        form = SupplierForm(instance=supplier)

    context = {
        'page_title': f'Modifier {supplier.name}',
        'form': form,
        'form_title': 'Modifier le fournisseur',
        'form_subtitle': f'Modifier les informations de {supplier.name}',
        'back_url': 'suppliers',
    }
    return render(request, 'core/supplier_form.html', context)


@login_required
@module_required('supplies')
def supplies(request):
    """Vue de la page des approvisionnements avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    supplier_id = request.GET.get('supplier', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)

    queryset = Supply.objects.filter(
        delete_at__isnull=True,
    ).select_related('product', 'supplier', 'staff', 'daily', 'credit_info')

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

    suppliers_for_filter = Supplier.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Approvisionnement',
        'page_obj': page_obj,
        'supplies': page_obj.object_list,
        'suppliers': suppliers_for_filter,
        'current_search': search,
        'current_supplier': supplier_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_count': paginator.count,
    }
    return render(request, 'core/supplies.html', context)


@login_required
@module_required('supplies')
def add_supply(request):
    """Vue pour ajouter un nouvel approvisionnement"""
    if request.method == 'POST':
        form = SupplyForm(request.POST)
        print(form.is_valid())
        print(form.errors)
        if form.is_valid():
            supply = form.save(commit=False)
            supply.staff = request.user
            supply.daily = DailyService.get_or_create_active_daily()
            supply.total_price = supply.quantity * supply.purchase_cost
            is_credit_purchase = form.cleaned_data.get('is_credit', False)
            supply.is_credit = is_credit_purchase
            supply.selling_price = form.cleaned_data.get('selling_price') or supply.product.actual_price or 0
            supply.is_paid = not is_credit_purchase
            
            # Calculer le montant de la TVA
            tax_rate = form.cleaned_data.get('tax_rate')
            if tax_rate:
                supply.vat_amount = supply.total_price * (tax_rate.rate / 100)
            else:
                supply.vat_amount = 0
            
            # Sauvegarder le type de dépense
            supply.expense_type = form.cleaned_data.get('expense_type')
            
            # Sauvegarder le type de dépense par défaut dans les paramètres système
            selected_expense_type = form.cleaned_data.get('expense_type')
            if selected_expense_type:
                from core.models.settings_models import SystemSettings
                settings = SystemSettings.get_settings()
                settings.default_supply_expense_type = selected_expense_type
                settings.save()
            
            supply.save()

            # Enregistrer l'écriture comptable
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            try:
                AccountingService.record_supply(
                    supply=supply,
                    daily=supply.daily,
                    exercise=supply.daily.exercise,
                    payment_method=payment_method,
                    is_credit=is_credit_purchase,
                    tax_rate=supply.tax_rate,  # Passer le taux de TVA depuis l'approvisionnement
                )
            except Exception:
                pass  # Ne pas bloquer l'approvisionnement si la comptabilité échoue

            # Créer CreditSupply + PaymentSchedule si achat à crédit
            if is_credit_purchase:
                due_date = form.cleaned_data.get('due_date')
                credit_supply = CreditSupply.objects.create(
                    supply=supply,
                    amount_paid=0,
                    amount_remaining=supply.total_price,
                    due_date=due_date,
                    is_fully_paid=False,
                )
                # Créer une échéance de paiement
                if due_date:
                    PaymentSchedule.objects.create(
                        schedule_type='SUPPLIER',
                        credit_supply=credit_supply,
                        due_date=due_date,
                        amount_due=supply.total_price,
                        status='PENDING',
                    )

            # Mettre à jour le stock du produit
            product = supply.product
            product.stock = (product.stock or 0) + supply.quantity
            # Mettre à jour le dernier prix d'achat
            product.last_purchase_price = supply.purchase_cost
            # Mettre à jour le prix de vente si renseigné
            selling_price = form.cleaned_data.get('selling_price')
            if selling_price:
                product.actual_price = selling_price
            product.save()

            # Retourner JSON si c'est une requête AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Approvisionnement de {supply.quantity} x "{product.name}" enregistré avec succès.',
                    'product_name': product.name,
                    'quantity': supply.quantity,
                    'purchase_cost': float(supply.purchase_cost),
                    'total_price': float(supply.total_price),
                    'vat_amount': float(supply.vat_amount) if supply.vat_amount else 0,
                    'expense_type_id': supply.expense_type_id if supply.expense_type else None,
                    'payment_method': payment_method,
                })

            messages.success(request, f'Approvisionnement de {supply.quantity} x "{product.name}" enregistré avec succès.')
            return redirect('supplies')
        else:
            form = SupplyForm(request.POST)  # Re-render form with errors
            return render(request, 'core/supplies_add.html', {
                'page_title': 'Nouvel approvisionnement',
                'form': form,
            })
    else:
        form = SupplyForm()

    context = {
        'page_title': 'Nouvel approvisionnement',
        'form': form,
    }
    return render(request, 'core/supplies_add.html', context)


@login_required
@module_required('expenses')
def expenses(request):
    """Vue de la page des dépenses et recettes quotidiennes avec pagination et filtres"""
    # Paramètres communs
    search = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    active_tab = request.GET.get('tab', 'expenses')
    
    # === DéPENSES ===
    expense_type_id = request.GET.get('expense_type', '')
    
    expenses_queryset = DailyExpense.objects.filter(
        delete_at__isnull=True,
    ).select_related('expense_type', 'staff', 'daily', 'exercise', 'account')

    if search:
        expenses_queryset = expenses_queryset.filter(
            Q(description__icontains=search) | Q(expense_type__name__icontains=search)
        )
    if expense_type_id:
        expenses_queryset = expenses_queryset.filter(expense_type_id=expense_type_id)
    if date_from:
        expenses_queryset = expenses_queryset.filter(create_at__date__gte=date_from)
    if date_to:
        expenses_queryset = expenses_queryset.filter(create_at__date__lte=date_to)

    expenses_queryset = expenses_queryset.order_by('-create_at')

    # Total des dépenses filtrées
    from django.db.models import Sum
    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or 0

    expenses_paginator = Paginator(expenses_queryset, 20)
    expenses_page = expenses_paginator.get_page(page_number)
    
    # === RECETTES ===
    recipe_type_id = request.GET.get('recipe_type', '')
    
    recipes_queryset = DailyRecipe.objects.filter(
        delete_at__isnull=True,
    ).select_related('recipe_type', 'staff', 'daily', 'exercise', 'account')
    
    if search:
        recipes_queryset = recipes_queryset.filter(
            Q(description__icontains=search) | Q(recipe_type__name__icontains=search)
        )
    if recipe_type_id:
        recipes_queryset = recipes_queryset.filter(recipe_type_id=recipe_type_id)
    if date_from:
        recipes_queryset = recipes_queryset.filter(create_at__date__gte=date_from)
    if date_to:
        recipes_queryset = recipes_queryset.filter(create_at__date__lte=date_to)
    
    recipes_queryset = recipes_queryset.order_by('-create_at')
    
    # Total des recettes filtrées
    total_recipes = recipes_queryset.aggregate(total=Sum('amount'))['total'] or 0
    
    recipes_paginator = Paginator(recipes_queryset, 20)
    recipes_page = recipes_paginator.get_page(page_number)

    expense_types = ExpenseType.objects.filter(delete_at__isnull=True).order_by('name')
    recipe_types = RecipeType.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Dépenses/Recettes',
        'active_tab': active_tab,
        # Dépenses
        'expenses': expenses_page.object_list,
        'expense_types': expense_types,
        'current_search': search,
        'current_expense_type': expense_type_id,
        'total_expenses': total_expenses,
        'expenses_page': expenses_page,
        'expenses_count': expenses_paginator.count,
        # Recettes
        'recipes': recipes_page.object_list,
        'recipe_types': recipe_types,
        'current_recipe_type': recipe_type_id,
        'total_recipes': total_recipes,
        'recipes_page': recipes_page,
        'recipes_count': recipes_paginator.count,
        # Filtres communs
        'current_date_from': date_from,
        'current_date_to': date_to,
    }
    return render(request, 'core/expenses.html', context)


@login_required
@module_required('expenses')
def add_expense(request):
    """Vue pour ajouter une nouvelle dépense"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            expense.daily = daily
            expense.exercise = daily.exercise
            expense.save()

            # Enregistrer l'écriture comptable
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            try:
                AccountingService.record_expense(
                    expense=expense,
                    daily=daily,
                    exercise=daily.exercise,
                    payment_method=payment_method,
                )
            except Exception:
                pass  # Ne pas bloquer la dépense si la comptabilité échoue

            messages.success(request, f'Dépense de {expense.amount:,.0f} FCFA enregistrée avec succès.')
            return redirect('expenses')
    else:
        # Pré-remplir les champs si des paramètres GET sont présents
        initial_data = {}

        if request.GET.get('amount'):
            initial_data['amount'] = request.GET.get('amount')

        if request.GET.get('description'):
            initial_data['description'] = request.GET.get('description')

        if request.GET.get('expense_type'):
            try:
                from core.models.accounting_models import ExpenseType
                expense_type = ExpenseType.objects.filter(
                    delete_at__isnull=True,
                    name__icontains=request.GET.get('expense_type')
                ).first()
                if expense_type:
                    initial_data['expense_type'] = expense_type.pk
            except (ValueError, ExpenseType.DoesNotExist):
                pass

        form = ExpenseForm(initial=initial_data)

    context = {
        'page_title': 'Nouvelle dépense',
        'form': form,
    }
    return render(request, 'core/expenses_add.html', context)


@require_POST
@login_required
@module_required('expenses')
def add_expense_ajax(request):
    """Vue AJAX pour ajouter une dépense depuis un approvisionnement"""
    try:
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            expense.daily = daily
            expense.exercise = daily.exercise
            expense.save()

            # Enregistrer l'écriture comptable
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            try:
                AccountingService.record_expense(
                    expense=expense,
                    daily=daily,
                    exercise=daily.exercise,
                    payment_method=payment_method,
                )
            except Exception:
                pass  # Ne pas bloquer la dépense si la comptabilité échoue

            return JsonResponse({
                'success': True,
                'message': f'Dépense de {expense.amount:,.0f}FCFA enregistrée avec succès.',
                'expense_id': expense.id,
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Formulaire invalide',
                'errors': form.errors,
            }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@login_required
@module_required('expenses')
def add_recipe(request):
    """Vue pour ajouter une nouvelle recette"""
    from core.forms import RecipeForm
    from core.models.accounting_models import DailyRecipe
    from core.services.accounting_service import AccountingService
    
    if request.method == 'POST':
        form = RecipeForm(request.POST)
        if form.is_valid():
            recipe = form.save(commit=False)
            recipe.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            recipe.daily = daily
            recipe.exercise = daily.exercise
            recipe.save()

            # Enregistrer l'écriture comptable
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            try:
                AccountingService.record_recipe(
                    recipe=recipe,
                    daily=daily,
                    exercise=daily.exercise,
                    payment_method=payment_method,
                )
            except Exception:
                pass  # Ne pas bloquer la recette si la comptabilité échoue

            messages.success(request, f'Recette de {recipe.amount:,.0f} FCFA enregistrée avec succès.')
            return redirect('expenses')
    else:
        form = RecipeForm()

    context = {
        'page_title': 'Nouvelle recette',
        'form': form,
    }
    return render(request, 'core/recipes_add.html', context)


@login_required
@module_required('reports')
def reports(request):
    """Vue de la page des rapports"""
    context = {
        'page_title': 'Rapports'
    }
    return render(request, 'core/reports.html', context)


@login_required
@module_required('dashboard')
def get_daily_summary(request):
    """API pour récupérer le résumé de la journée en cours"""
    from core.models.inventory_models import DailyInventory

    current_daily = DailyService.get_or_create_active_daily()

    if not current_daily:
        return JsonResponse({'success': False, 'message': 'Aucune journée active trouvée.'}, status=404)

    # Calculer les totaux
    total_sales = Sale.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('total'))['total'] or 0

    total_expenses = DailyExpense.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    from core.models.accounting_models import DailyRecipe
    total_recipes = DailyRecipe.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Récupérer le fond de caisse de la journée précédente
    previous_inventory = DailyInventory.objects.filter(
        delete_at__isnull=True
    ).exclude(daily=current_daily).order_by('-create_at').first()

    previous_cash_float = float(previous_inventory.cash_float) if previous_inventory else 0

    # Cash attendu = fond de caisse précédent + ventes - dépenses
    expected_cash = previous_cash_float + float(total_sales) - float(total_expenses)

    return JsonResponse({
        'success': True,
        'total_sales': float(total_sales),
        'total_expenses': float(total_expenses),
        'total_recipes': float(total_recipes),
        'previous_cash_float': previous_cash_float,
        'expected_cash': expected_cash,
        'daily_id': current_daily.id,
        'daily_date': current_daily.start_date.strftime('%d/%m/%Y'),
    })


@login_required
@module_required('dashboard')
@require_POST
def close_daily(request):
    """Vue pour clôturer la journée et créer un DailyInventory"""
    import json
    from core.models.inventory_models import DailyInventory

    current_daily = DailyService.get_or_create_active_daily()

    if not current_daily:
        return JsonResponse({'success': False, 'message': 'Aucune journée active trouvée.'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Données invalides.'}, status=400)

    cash_in_hand = data.get('cash_in_hand', 0)
    cash_float = data.get('cash_float', 0)
    notes = data.get('notes', '')

    try:
        cash_in_hand = float(cash_in_hand)
        cash_float = float(cash_float)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Les montants doivent être des nombres valides.'}, status=400)

    # Calculer les totaux
    total_sales = Sale.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('total'))['total'] or 0

    total_expenses = DailyExpense.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    from core.models.accounting_models import DailyRecipe
    total_recipes = DailyRecipe.objects.filter(
        daily=current_daily, delete_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Créer le DailyInventory
    daily_inventory = DailyInventory.objects.create(
        daily=current_daily,
        staff=request.user,
        exercise=current_daily.exercise,
        total_sales=total_sales,
        total_expenses=total_expenses,
        total_recipes=total_recipes,
        cash_in_hand=cash_in_hand,
        cash_float=cash_float,
        notes=notes,
    )

    # Fermer la journée
    DailyService.close_current_daily()
    
    # Traiter la TVA différée si le mode est DEFERRED
    from core.models.settings_models import SystemSettings
    settings = SystemSettings.get_settings()
    tva_mode = getattr(settings, 'tva_accounting_mode', 'IMMEDIATE')
    enable_tva = getattr(settings, 'enable_tva_accounting', True)
    
    tva_entries_created = 0
    if enable_tva and tva_mode == 'DEFERRED':
        from core.services.accounting_service import AccountingService
        tva_entries_created = AccountingService.record_deferred_tva_for_daily(current_daily)

    return JsonResponse({
        'success': True,
        'message': 'La journée a été clôturée avec succès.',
        'daily_inventory_id': daily_inventory.id,
        'tva_entries_created': tva_entries_created,
    })


@login_required
@module_required('settings')
def settings(request):
    """Vue de la page des paramètres"""
    context = {
        'page_title': 'Paramètres'
    }
    return render(request, 'core/settings.html', context)


@login_required
@module_required('settings')
def data_migration(request):
    """Vue pour migrer les données de l'ancien système"""
    from core.services.migration_service import migrate_data

    migration_stats = None

    if request.method == 'POST':
        form = DataMigrationForm(request.POST)
        if form.is_valid():
            try:
                stats = migrate_data(
                    products_sql=form.cleaned_data.get('products_sql', ''),
                    images_sql=form.cleaned_data.get('images_sql', ''),
                    categories_sql=form.cleaned_data.get('categories_sql', ''),
                    gammes_sql=form.cleaned_data.get('gammes_sql', ''),
                    rayons_sql=form.cleaned_data.get('rayons_sql', ''),
                    grammage_types_sql=form.cleaned_data.get('grammage_types_sql', ''),
                )
                migration_stats = stats
                total = (
                    stats['categories'] + stats['gammes'] + stats['rayons']
                    + stats['grammage_types'] + stats['products'] + stats['images']
                )
                messages.success(
                    request,
                    f"Migration terminée avec succès ! {total} éléments créés."
                )
            except Exception as e:
                messages.error(request, f"Erreur lors de la migration : {str(e)}")
    else:
        form = DataMigrationForm()

    context = {
        'page_title': 'Migration de données',
        'form': form,
        'migration_stats': migration_stats,
    }
    return render(request, 'core/data_migration.html', context)



# ══════════════════════════════════════════════════════════════════════════════
# VUES COMPTABLES
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@module_required('accounting')
def accounting_journal(request):
    """Vue du journal comptable — liste de toutes les écritures."""
    from core.models.accounting_models import JournalEntry, JournalEntryLine, Account

    # Filtres
    journal_filter = request.GET.get('journal', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '')

    entries = JournalEntry.objects.filter(
        delete_at__isnull=True,
    ).select_related('exercise', 'daily').prefetch_related('lines__account').order_by('-date', '-create_at')

    if journal_filter:
        entries = entries.filter(journal=journal_filter)
    if date_from:
        entries = entries.filter(date__gte=date_from)
    if date_to:
        entries = entries.filter(date__lte=date_to)
    if search:
        entries = entries.filter(
            Q(reference__icontains=search) | Q(description__icontains=search)
        )

    paginator = Paginator(entries, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Totaux
    total_debit = sum(
        line.debit for entry in page_obj for line in entry.lines.all()
    )
    total_credit = sum(
        line.credit for entry in page_obj for line in entry.lines.all()
    )

    context = {
        'page_title': 'Journal comptable',
        'page_obj': page_obj,
        'entries': page_obj.object_list,
        'journal_choices': JournalEntry.JOURNAL_CHOICES,
        'current_journal': journal_filter,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'current_search': search,
        'total_count': paginator.count,
        'total_debit': total_debit,
        'total_credit': total_credit,
    }
    return render(request, 'core/accounting/journal.html', context)


@login_required
@module_required('accounting')
def accounting_general_ledger(request):
    """Vue du grand livre — détail d'un compte avec solde progressif."""
    from core.models.accounting_models import Account

    accounts = Account.objects.filter(
        is_active=True, delete_at__isnull=True
    ).order_by('code')

    account_code = request.GET.get('account', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    selected_account = None
    ledger_lines = []
    total_debit = 0
    total_credit = 0
    balance = 0

    if account_code:
        selected_account = Account.objects.filter(code=account_code, delete_at__isnull=True).first()
        if selected_account:
            exercise = ExerciseService.get_or_create_current_exercise()
            ledger_lines = AccountingService.get_general_ledger(selected_account, exercise)

            # Filtrer par date si nécessaire
            if date_from or date_to:
                filtered = []
                from decimal import Decimal
                running = Decimal('0')
                for item in ledger_lines:
                    line = item['line']
                    entry_date = str(line.entry.date)
                    if date_from and entry_date < date_from:
                        continue
                    if date_to and entry_date > date_to:
                        continue
                    if selected_account.account_type in ('ACTIF', 'CHARGE'):
                        running += line.debit - line.credit
                    else:
                        running += line.credit - line.debit
                    filtered.append({'line': line, 'running_balance': running})
                ledger_lines = filtered

            total_debit = sum(item['line'].debit for item in ledger_lines)
            total_credit = sum(item['line'].credit for item in ledger_lines)
            balance = ledger_lines[-1]['running_balance'] if ledger_lines else 0

    context = {
        'page_title': 'Grand Livre',
        'accounts': accounts,
        'selected_account': selected_account,
        'ledger_lines': ledger_lines,
        'current_account': account_code,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'balance': balance,
    }
    return render(request, 'core/accounting/general_ledger.html', context)


@login_required
@module_required('accounting')
def accounting_trial_balance(request):
    """Vue de la balance générale — solde de tous les comptes."""
    exercise = ExerciseService.get_or_create_current_exercise()
    trial_balance = AccountingService.get_trial_balance(exercise)

    total_debit = sum(item['total_debit'] for item in trial_balance)
    total_credit = sum(item['total_credit'] for item in trial_balance)

    context = {
        'page_title': 'Balance générale',
        'trial_balance': trial_balance,
        'exercise': exercise,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'is_balanced': total_debit == total_credit,
    }
    return render(request, 'core/accounting/trial_balance.html', context)


@login_required
@module_required('accounting')
def accounting_chart_of_accounts(request):
    """Vue du plan comptable."""
    from core.models.accounting_models import Account

    accounts = Account.objects.filter(
        is_active=True, delete_at__isnull=True
    ).order_by('code')

    # Regrouper par classe
    classes = {}
    for account in accounts:
        class_num = account.code[0] if account.code else '?'
        class_names = {
            '1': 'Capitaux',
            '2': 'Immobilisations',
            '3': 'Stocks',
            '4': 'Tiers',
            '5': 'Trésorerie',
            '6': 'Charges',
            '7': 'Produits',
        }
        class_label = class_names.get(class_num, 'Autres')
        if class_num not in classes:
            classes[class_num] = {'label': class_label, 'accounts': []}
        classes[class_num]['accounts'].append(account)

    context = {
        'page_title': 'Plan comptable',
        'classes': dict(sorted(classes.items())),
        'total_accounts': accounts.count(),
    }
    return render(request, 'core/accounting/chart_of_accounts.html', context)


@login_required
@module_required('accounting')
def export_chart_of_accounts(request):
    """Export du plan comptable en CSV ou TXT."""
    import csv
    from django.http import HttpResponse
    
    format_type = request.GET.get('format', 'csv')
    
    # Définir le delimiter selon le format
    delimiter = ';' if format_type == 'csv' else '\t'
    
    accounts = Account.objects.filter(
        is_active=True, delete_at__isnull=True
    ).order_by('code')
    
    response = HttpResponse(content_type=f'text/{format_type}; charset=utf-8')
    response.write('\ufeff')  # BOM UTF-8 pour Excel
    writer = csv.writer(response, delimiter=delimiter)
    
    # En-tête
    filename = f"plan_comptable.{format_type}"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # En-têtes CSV
    writer.writerow(['Code', 'Libellé', 'Type', 'Compte Parent', 'Description', 'Actif'])
    
    # Données
    for account in accounts:
        parent_code = account.parent.code if account.parent else ''
        writer.writerow([
            account.code,
            account.name,
            account.account_type,
            parent_code,
            account.description or '',
            'Oui' if account.is_active else 'Non'
        ])
    
    return response


@login_required
@module_required('accounting')
def import_chart_of_accounts(request):
    """Import du plan comptable depuis CSV ou TXT."""
    from django.contrib import messages
    from django.shortcuts import redirect
    import csv
    import io
    
    if request.method != 'POST':
        messages.error(request, "Méthode non autorisée.")
        return redirect('accounting_chart')
    
    file = request.FILES.get('file')
    if not file:
        messages.error(request, "Aucun fichier sélectionné.")
        return redirect('accounting_chart')
    
    # Vérifier l'extension
    filename = file.name.lower()
    if not (filename.endswith('.csv') or filename.endswith('.txt')):
        messages.error(request, "Le fichier doit être au format CSV ou TXT.")
        return redirect('accounting_chart')
    
    delimiter = ';' if filename.endswith('.csv') else '\t'
    
    try:
        # Lire le fichier
        decoded = file.read().decode('utf-8-sig')
        reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
        
        # Sauter l'en-tête
        header = next(reader, None)
        
        accounts_created = 0
        accounts_updated = 0
        errors = []
        
        for row_num, row in enumerate(reader, start=2):
            if not row or len(row) < 3:
                continue
            
            try:
                code = row[0].strip()
                name = row[1].strip()
                account_type = row[2].strip().upper()
                
                # Valider le type de compte
                valid_types = ['ACTIF', 'PASSIF', 'CHARGE', 'PRODUIT']
                if account_type not in valid_types:
                    errors.append(f"Ligne {row_num}: Type de compte invalide '{account_type}'")
                    continue
                
                # Vérifier si le compte existe déjà
                parent_code = row[3].strip() if len(row) > 3 else ''
                description = row[4].strip() if len(row) > 4 else ''
                is_active = row[5].strip().lower() != 'non' if len(row) > 5 else True
                
                # Chercher le parent
                parent = None
                if parent_code:
                    try:
                        parent = Account.objects.get(code=parent_code, delete_at__isnull=True)
                    except Account.DoesNotExist:
                        errors.append(f"Ligne {row_num}: Compte parent '{parent_code}' introuvable")
                        continue
                
                # Créer ou mettre à jour
                account, created = Account.objects.update_or_create(
                    code=code,
                    defaults={
                        'name': name,
                        'account_type': account_type,
                        'parent': parent,
                        'description': description,
                        'is_active': is_active,
                    }
                )
                
                if created:
                    accounts_created += 1
                else:
                    accounts_updated += 1
                    
            except Exception as e:
                errors.append(f"Ligne {row_num}: {str(e)}")
        
        # Message de succès/erreur
        if accounts_created > 0:
            messages.success(request, f"{accounts_created} compte(s) créé(s).")
        if accounts_updated > 0:
            messages.success(request, f"{accounts_updated} compte(s) mis à jour.")
        if errors:
            for error in errors[:10]:  # Limiter à 10 erreurs affichées
                messages.warning(request, error)
            if len(errors) > 10:
                messages.warning(request, f"... et {len(errors) - 10} erreur(s) supplémentaire(s).")
        
    except Exception as e:
        messages.error(request, f"Erreur lors de l'importation: {str(e)}")
    
    return redirect('accounting_chart')


@login_required
@module_required('accounting')
def accounting_add_entry(request):
    """Vue pour ajouter une écriture comptable manuelle (Opérations Diverses)."""
    from core.forms import JournalEntryForm
    from core.models.accounting_models import Account, JournalEntry, JournalEntryLine, Exercise
    from core.services.accounting_service import AccountingService
    from decimal import Decimal
    
    accounts = Account.objects.filter(
        is_active=True, delete_at__isnull=True
    ).order_by('code')
    
    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        
        # Récupérer les lignes
        line_count = int(request.POST.get('line_count', 2))
        lines_data = []
        errors = []
        
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        
        for i in range(line_count):
            account_id = request.POST.get(f'account_{i}')
            debit = request.POST.get(f'debit_{i}', '0').replace(',', '.')
            credit = request.POST.get(f'credit_{i}', '0').replace(',', '.')
            line_desc = request.POST.get(f'line_desc_{i}', '')
            
            if not account_id:
                continue
                
            try:
                debit_val = Decimal(debit) if debit else Decimal('0')
                credit_val = Decimal(credit) if credit else Decimal('0')
                
                # Au moins un montant doit être positif
                if debit_val == 0 and credit_val == 0:
                    continue
                    
                # Les deux ne peuvent pas être positifs
                if debit_val > 0 and credit_val > 0:
                    errors.append(f"Ligne {i+1}: Un compte ne peut pas avoir à la fois un débit et un crédit.")
                    continue
                    
                total_debit += debit_val
                total_credit += credit_val
                
                lines_data.append({
                    'account_id': int(account_id),
                    'debit': debit_val,
                    'credit': credit_val,
                    'description': line_desc
                })
                
            except Exception as e:
                errors.append(f"Ligne {i+1}: {str(e)}")
        
        # Validation
        if not form.is_valid():
            errors.extend([f"{k}: {v[0]}" for k, v in form.errors.items()])
        
        if not lines_data:
            errors.append("Veuillez saisir au moins une ligne avec un montant.")
        
        if total_debit != total_credit:
            errors.append(f"L'écriture n'est pas équilibrée. Total débit: {total_debit}, Total crédit: {total_credit}")
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Créer l'écriture
            try:
                exercise = ExerciseService.get_or_create_current_exercise()
                ref = AccountingService._generate_reference('OD')  # OD = Opérations Diverses
                
                entry = JournalEntry.objects.create(
                    reference=ref,
                    date=form.cleaned_data['date'],
                    description=form.cleaned_data['description'],
                    journal='OD',  # Journal des Opérations Diverses
                    exercise=exercise,
                    is_validated=True,
                )
                
                # Créer les lignes
                for line_data in lines_data:
                    JournalEntryLine.objects.create(
                        entry=entry,
                        account_id=line_data['account_id'],
                        debit=line_data['debit'],
                        credit=line_data['credit'],
                        description=line_data['description'],
                    )
                
                messages.success(request, f"Écriture {ref} créée avec succès!")
                return redirect('accounting_journal')
                
            except Exception as e:
                messages.error(request, f"Erreur lors de la création: {str(e)}")
    else:
        form = JournalEntryForm()
    
    context = {
        'page_title': 'Nouvelle écriture comptable',
        'form': form,
        'accounts': accounts,
        'journal_choices': JournalEntry.JOURNAL_CHOICES,
    }
    return render(request, 'core/accounting/add_entry.html', context)
# ║            Tableau de bord trésorerie                              ║
# ╚══════════════════════════════════════════════════════════════════════╝


@login_required
@module_required('treasury')
def credit_sales_list(request):
    """Vue listant les ventes à crédit avec leur statut de paiement."""
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    queryset = CreditSale.objects.select_related(
        'sale', 'sale__client', 'sale__staff', 'sale__daily',
    ).filter(
        delete_at__isnull=True, sale__delete_at__isnull=True,
    ).order_by('-sale__create_at')

    if search:
        queryset = queryset.filter(
            Q(sale__client__firstname__icontains=search)
            | Q(sale__client__lastname__icontains=search)
            | Q(sale__id__icontains=search)
        )
    if status_filter == 'paid':
        queryset = queryset.filter(is_fully_paid=True)
    elif status_filter == 'unpaid':
        queryset = queryset.filter(is_fully_paid=False)

    total_credit = queryset.aggregate(t=Sum('sale__total'))['t'] or 0
    total_paid = queryset.aggregate(t=Sum('amount_paid'))['t'] or 0
    total_remaining = queryset.aggregate(t=Sum('amount_remaining'))['t'] or 0

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Ventes à crédit',
        'page_obj': page_obj,
        'credit_sales': page_obj.object_list,
        'current_search': search,
        'current_status': status_filter,
        'total_count': paginator.count,
        'total_credit': total_credit,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
    }
    return render(request, 'core/accounting/credit_sales.html', context)


@login_required
@module_required('treasury')
def record_credit_payment(request, credit_sale_id):
    """Vue pour enregistrer un paiement sur une vente à crédit."""
    credit_sale = get_object_or_404(
        CreditSale.objects.select_related('sale', 'sale__client'),
        id=credit_sale_id, delete_at__isnull=True,
    )

    if credit_sale.is_fully_paid:
        messages.warning(request, 'Cette vente à crédit est déjà entièrement payée.')
        return redirect('credit_sales')

    if request.method == 'POST':
        form = PaymentForm(request.POST, credit_sale=credit_sale)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.credit_sale = credit_sale
            payment.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            payment.daily = daily
            payment.save()

            # Mettre à jour le CreditSale
            credit_sale.amount_paid += payment.amount
            credit_sale.amount_remaining -= payment.amount
            if credit_sale.amount_remaining <= 0:
                credit_sale.amount_remaining = 0
                credit_sale.is_fully_paid = True
                credit_sale.sale.is_paid = True
                credit_sale.sale.save(update_fields=['is_paid'])
            credit_sale.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])

            # Écriture comptable
            try:
                exercise = daily.exercise if daily else ExerciseService.get_or_create_current_exercise()
                AccountingService.record_credit_payment(
                    payment=payment,
                    daily=daily,
                    exercise=exercise,
                )
            except Exception:
                pass

            messages.success(
                request,
                f'Paiement de {payment.amount:,.0f} FCFA enregistré. '
                f'Solde restant : {credit_sale.amount_remaining:,.0f} FCFA.'
            )
            return redirect('credit_sales')
    else:
        form = PaymentForm(credit_sale=credit_sale)

    # Historique des paiements sur cette vente
    payments = credit_sale.payments.filter(delete_at__isnull=True).order_by('-payment_date')

    context = {
        'page_title': f'Paiement – Vente #{credit_sale.sale_id}',
        'form': form,
        'credit_sale': credit_sale,
        'payments': payments,
    }
    return render(request, 'core/accounting/record_payment.html', context)


@login_required
@module_required('treasury')
def supplier_payments_list(request):
    """Vue listant les paiements fournisseurs."""
    search = request.GET.get('search', '')
    supplier_id = request.GET.get('supplier', '')

    queryset = SupplierPayment.objects.select_related(
        'supplier', 'supply', 'staff', 'daily',
    ).filter(delete_at__isnull=True).order_by('-payment_date', '-create_at')

    if search:
        queryset = queryset.filter(
            Q(supplier__name__icontains=search)
            | Q(reference__icontains=search)
        )
    if supplier_id:
        queryset = queryset.filter(supplier_id=supplier_id)

    total_amount = queryset.aggregate(t=Sum('amount'))['t'] or 0

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    suppliers = Supplier.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Paiements fournisseurs',
        'page_obj': page_obj,
        'supplier_payments': page_obj.object_list,
        'suppliers': suppliers,
        'current_search': search,
        'current_supplier': supplier_id,
        'total_count': paginator.count,
        'total_amount': total_amount,
    }
    return render(request, 'core/accounting/supplier_payments.html', context)


@login_required
@module_required('treasury')
def add_supplier_payment(request):
    """Vue pour enregistrer un paiement fournisseur."""
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            payment.daily = daily
            payment.save()

            # Écriture comptable
            try:
                exercise = daily.exercise if daily else ExerciseService.get_or_create_current_exercise()
                AccountingService.record_supplier_payment(
                    supplier_payment=payment,
                    daily=daily,
                    exercise=exercise,
                )
            except Exception:
                pass

            messages.success(
                request,
                f'Paiement de {payment.amount:,.0f} FCFA à {payment.supplier.name} enregistré.'
            )
            return redirect('supplier_payments')
    else:
        form = SupplierPaymentForm()

    context = {
        'page_title': 'Nouveau paiement fournisseur',
        'form': form,
    }
    return render(request, 'core/accounting/add_supplier_payment.html', context)


@login_required
@module_required('treasury')
def record_supply_payment(request, supply_id):
    """Vue pour enregistrer un paiement pour un approvisionnement à crédit spécifique."""
    from core.models.inventory_models import CreditSupply
    
    supply = get_object_or_404(Supply, id=supply_id, delete_at__isnull=True)
    
    if not supply.is_credit:
        messages.warning(request, 'Cet approvisionnement n\'est pas un achat à crédit.')
        return redirect('supplies')
    
    # Récupérer ou créer le CreditSupply
    try:
        credit_supply = supply.credit_info
    except CreditSupply.DoesNotExist:
        credit_supply = CreditSupply.objects.create(
            supply=supply,
            amount_paid=0,
            amount_remaining=supply.total_price,
            is_fully_paid=False,
        )
    
    if credit_supply.is_fully_paid:
        messages.warning(request, 'Cet approvisionnement est déjà payé.')
        return redirect('supplies')

    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.staff = request.user
            daily = DailyService.get_or_create_active_daily()
            payment.daily = daily
            payment.save()

            # Mettre à jour le CreditSupply
            credit_supply.amount_paid += payment.amount
            credit_supply.amount_remaining -= payment.amount
            
            # Vérifier si le paiement est complet
            if credit_supply.amount_remaining <= 0:
                credit_supply.amount_remaining = 0
                credit_supply.is_fully_paid = True
                supply.is_paid = True
                supply.save(update_fields=['is_paid'])
            
            credit_supply.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])

            # Écriture comptable
            try:
                exercise = daily.exercise if daily else ExerciseService.get_or_create_current_exercise()
                AccountingService.record_supplier_payment(
                    supplier_payment=payment,
                    daily=daily,
                    exercise=exercise,
                )
            except Exception:
                pass

            messages.success(
                request,
                f'Paiement de {payment.amount:,.0f} FCFA pour {supply.product.name} enregistré. '
                f'Restant: {credit_supply.amount_remaining:,.0f} FCFA'
            )
            return redirect('supplies')
    else:
        # Pré-remplir le formulaire avec le montant restant
        initial_data = {
            'amount': credit_supply.amount_remaining,
            'supplier': supply.supplier,
        }
        form = SupplierPaymentForm(initial=initial_data)

    # Historique des paiements pour ce fournisseur
    payments = SupplierPayment.objects.filter(
        supplier=supply.supplier, delete_at__isnull=True
    ).order_by('-payment_date')[:5]

    context = {
        'page_title': f'Paiement – {supply.product.name}',
        'form': form,
        'supply': supply,
        'credit_supply': credit_supply,
        'payments': payments,
    }
    return render(request, 'core/accounting/record_supply_payment.html', context)


@login_required
@module_required('treasury')
def invoices_list(request):
    """Vue listant les factures."""
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    queryset = Invoice.objects.select_related(
        'sale', 'sale__client', 'sale__staff',
    ).filter(delete_at__isnull=True).order_by('-invoice_date', '-create_at')

    if search:
        queryset = queryset.filter(
            Q(invoice_number__icontains=search)
            | Q(sale__client__firstname__icontains=search)
            | Q(sale__client__lastname__icontains=search)
        )
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Factures',
        'page_obj': page_obj,
        'invoices': page_obj.object_list,
        'current_search': search,
        'current_status': status_filter,
        'total_count': paginator.count,
    }
    return render(request, 'core/accounting/invoices.html', context)


@login_required
@module_required('treasury')
def generate_invoice(request, sale_id):
    """Génère une facture pour une vente."""
    sale = get_object_or_404(Sale, id=sale_id, delete_at__isnull=True)

    # Vérifier qu'il n'y a pas déjà une facture
    if hasattr(sale, 'invoice') and sale.invoice and sale.invoice.delete_at is None:
        messages.info(request, f'Facture {sale.invoice.invoice_number} existe déjà pour cette vente.')
        return redirect('invoices')

    invoice = Invoice.objects.create(
        sale=sale,
        invoice_number=Invoice.generate_invoice_number(),
        invoice_date=timezone.now().date(),
        due_date=getattr(sale, 'credit_info', None) and sale.credit_info.due_date,
        status='PAID' if sale.is_paid else 'SENT',
    )

    messages.success(request, f'Facture {invoice.invoice_number} générée avec succès.')
    return redirect('invoices')


@login_required
@module_required('treasury')
def treasury_dashboard(request):
    """Tableau de bord de la trésorerie — solde de chaque compte de trésorerie."""
    from decimal import Decimal

    exercise = ExerciseService.get_or_create_current_exercise()

    # Comptes de trésorerie (classe 5)
    treasury_codes = ['571', '521', '585']
    treasury_accounts = []
    total_treasury = Decimal('0')

    for code in treasury_codes:
        try:
            account = Account.objects.get(code=code, delete_at__isnull=True)
            balance = account.get_balance(exercise)
            treasury_accounts.append({
                'account': account,
                'balance': balance,
            })
            total_treasury += balance
        except Account.DoesNotExist:
            pass

    # Créances clients (411)
    try:
        clients_account = Account.objects.get(code='411', delete_at__isnull=True)
        clients_balance = clients_account.get_balance(exercise)
    except Account.DoesNotExist:
        clients_balance = Decimal('0')

    # Dettes fournisseurs (401)
    try:
        suppliers_account = Account.objects.get(code='401', delete_at__isnull=True)
        suppliers_balance = suppliers_account.get_balance(exercise)
    except Account.DoesNotExist:
        suppliers_balance = Decimal('0')

    # Derniers paiements reçus
    recent_payments = Payment.objects.filter(
        delete_at__isnull=True,
    ).select_related('credit_sale__sale__client').order_by('-payment_date', '-create_at')[:10]

    # Derniers paiements fournisseurs
    recent_supplier_payments = SupplierPayment.objects.filter(
        delete_at__isnull=True,
    ).select_related('supplier').order_by('-payment_date', '-create_at')[:10]

    context = {
        'page_title': 'Trésorerie',
        'treasury_accounts': treasury_accounts,
        'total_treasury': total_treasury,
        'clients_balance': clients_balance,
        'suppliers_balance': suppliers_balance,
        'recent_payments': recent_payments,
        'recent_supplier_payments': recent_supplier_payments,
        'exercise': exercise,
    }
    return render(request, 'core/accounting/treasury.html', context)


# ═══════════════════════════════════════════════════════════════════
# Phase 3 — Rapports financiers
# ═══════════════════════════════════════════════════════════════════


@login_required
@module_required('reports')
def income_statement(request):
    """Compte de résultat."""
    exercise = ExerciseService.get_or_create_current_exercise()
    data = AccountingService.get_income_statement(exercise)

    context = {
        'page_title': 'Compte de résultat',
        'exercise': exercise,
        **data,
    }
    return render(request, 'core/accounting/income_statement.html', context)


@login_required
@module_required('reports')
def balance_sheet(request):
    """Bilan comptable."""
    exercise = ExerciseService.get_or_create_current_exercise()
    data = AccountingService.get_balance_sheet(exercise)

    context = {
        'page_title': 'Bilan comptable',
        'exercise': exercise,
        **data,
    }
    return render(request, 'core/accounting/balance_sheet.html', context)


@login_required
@module_required('reports')
def aged_balance(request):
    """Balance âgée (clients ou fournisseurs)."""
    balance_type = request.GET.get('type', 'client')
    exercise = ExerciseService.get_or_create_current_exercise()
    data = AccountingService.get_aged_balance(balance_type, exercise)

    print(data)
    context = {
        'page_title': f"Balance âgée — {data['title']}",
        'exercise': exercise,
        'current_type': balance_type,
        **data,
    }
    return render(request, 'core/accounting/aged_balance.html', context)


@login_required
@module_required('reports')
def product_margins(request):
    """Rapport de marge par produit."""
    exercise = ExerciseService.get_or_create_current_exercise()
    data = AccountingService.get_product_margins(exercise)

    context = {
        'page_title': 'Marge par produit',
        'exercise': exercise,
        **data,
    }
    return render(request, 'core/accounting/product_margins.html', context)


@login_required
@module_required('reports')
def export_report_csv(request, report_type):
    """Export CSV d'un rapport financier."""
    import csv
    from django.http import HttpResponse

    exercise = ExerciseService.get_or_create_current_exercise()

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response.write('\ufeff')  # BOM UTF-8 pour Excel
    writer = csv.writer(response, delimiter=';')

    if report_type == 'income_statement':
        response['Content-Disposition'] = 'attachment; filename="compte_de_resultat.csv"'
        data = AccountingService.get_income_statement(exercise)
        writer.writerow(['Compte de résultat', f'Exercice {exercise}'])
        writer.writerow([])
        writer.writerow(['PRODUITS'])
        writer.writerow(['Code', 'Intitulé', 'Montant'])
        for item in data['produits']:
            writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', 'TOTAL PRODUITS', str(data['total_produits'])])
        writer.writerow([])
        writer.writerow(['CHARGES'])
        writer.writerow(['Code', 'Intitulé', 'Montant'])
        for item in data['charges']:
            writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', 'TOTAL CHARGES', str(data['total_charges'])])
        writer.writerow([])
        writer.writerow(['', 'RÉSULTAT NET', str(data['resultat_net'])])

    elif report_type == 'balance_sheet':
        response['Content-Disposition'] = 'attachment; filename="bilan_comptable.csv"'
        data = AccountingService.get_balance_sheet(exercise)
        writer.writerow(['Bilan comptable', f'Exercice {exercise}'])
        writer.writerow([])
        writer.writerow(['ACTIF'])
        writer.writerow(['Code', 'Intitulé', 'Montant'])
        for section in [data['actif_immobilise'], data['actif_circulant'], data['tresorerie_actif']]:
            for item in section:
                writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', 'TOTAL ACTIF', str(data['total_actif'])])
        writer.writerow([])
        writer.writerow(['PASSIF'])
        writer.writerow(['Code', 'Intitulé', 'Montant'])
        for section in [data['capitaux'], data['dettes'], data['tresorerie_passif']]:
            for item in section:
                writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        if data['resultat_net'] > 0:
            writer.writerow(['', 'Résultat de l\'exercice', str(data['resultat_net'])])
        writer.writerow(['', 'TOTAL PASSIF', str(data['total_passif'])])

    elif report_type == 'product_margins':
        response['Content-Disposition'] = 'attachment; filename="marges_produits.csv"'
        data = AccountingService.get_product_margins(exercise)
        writer.writerow(['Marge par produit', f'Exercice {exercise}'])
        writer.writerow([])
        writer.writerow(['Produit', 'Qté vendue', 'CA (FCFA)', 'Prix achat', 'Coût total', 'Marge', 'Marge %'])
        for item in data['items']:
            writer.writerow([
                item['product'].name, item['qty_sold'],
                str(item['revenue']), str(item['purchase_price']),
                str(item['cost']), str(item['margin']),
                f"{item['margin_pct']:.1f}%",
            ])
        writer.writerow([])
        writer.writerow(['TOTAUX', '', str(data['total_ca']), '',
                         str(data['total_cost']), str(data['total_margin']),
                         f"{data['total_margin_pct']:.1f}%"])

    elif report_type == 'aged_balance':
        balance_type = request.GET.get('type', 'client')
        response['Content-Disposition'] = f'attachment; filename="balance_agee_{balance_type}.csv"'
        data = AccountingService.get_aged_balance(balance_type, exercise)
        writer.writerow([data['title'], f'Exercice {exercise}'])
        writer.writerow([])
        writer.writerow(['Référence', 'Tiers', 'Date', 'Échéance', 'Jours', 'Tranche', 'Montant'])
        for item in data['items']:
            writer.writerow([
                item['reference'], item['tiers'],
                item['date'].strftime('%d/%m/%Y') if item['date'] else '',
                item['due_date'].strftime('%d/%m/%Y') if item['due_date'] else '',
                item['age_days'], item['tranche'], str(item['amount']),
            ])
        writer.writerow([])
        writer.writerow(['', '', '', '', '', 'TOTAL', str(data['grand_total'])])

    else:
        return HttpResponse('Type de rapport inconnu', status=400)

    return response


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 — TVA, Rapprochement bancaire, Clôture d'exercice
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@module_required('accounting')
def vat_declaration(request):
    """Déclaration de TVA."""
    exercise = ExerciseService.get_or_create_current_exercise()
    data = AccountingService.get_vat_declaration(exercise)

    context = {
        'page_title': 'Déclaration de TVA',
        'exercise': exercise,
        **data,
    }
    return render(request, 'core/accounting/vat_declaration.html', context)


@login_required
@module_required('accounting')
def bank_reconciliation(request):
    """Rapprochement bancaire."""
    account_code = request.GET.get('account', '521')
    date_start = request.GET.get('date_start')
    date_end = request.GET.get('date_end')

    # Convertir les dates
    from datetime import datetime as dt
    d_start = dt.strptime(date_start, '%Y-%m-%d').date() if date_start else None
    d_end = dt.strptime(date_end, '%Y-%m-%d').date() if date_end else None

    try:
        data = AccountingService.get_bank_reconciliation(account_code, d_start, d_end)
    except Account.DoesNotExist:
        from django.http import Http404
        raise Http404("Compte bancaire introuvable")

    # Comptes bancaires disponibles pour le sélecteur
    bank_accounts = Account.objects.filter(
        code__in=['521', '585'], delete_at__isnull=True
    )

    context = {
        'page_title': 'Rapprochement bancaire',
        'bank_accounts': bank_accounts,
        'current_account': account_code,
        'date_start': date_start or '',
        'date_end': date_end or '',
        **data,
    }
    return render(request, 'core/accounting/bank_reconciliation.html', context)


@login_required
@module_required('accounting')
def reconcile_entry(request):
    """Rapprocher une ligne de relevé avec une écriture (POST AJAX)."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    statement_id = request.POST.get('statement_id')
    entry_line_id = request.POST.get('entry_line_id')

    if not statement_id or not entry_line_id:
        return JsonResponse({'error': 'Paramètres manquants'}, status=400)

    try:
        stmt = AccountingService.reconcile_statement(
            int(statement_id), int(entry_line_id), user=request.user
        )
        return JsonResponse({
            'success': True,
            'message': f'Ligne rapprochée avec succès',
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@module_required('accounting')
def unreconcile_entry(request):
    """Annuler le rapprochement d'une ligne (POST AJAX)."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    statement_id = request.POST.get('statement_id')
    if not statement_id:
        return JsonResponse({'error': 'Paramètre manquant'}, status=400)

    try:
        AccountingService.unreconcile_statement(int(statement_id))
        return JsonResponse({'success': True, 'message': 'Rapprochement annulé'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@module_required('accounting')
def exercise_closing_view(request):
    """Page de clôture d'exercice."""
    exercise = ExerciseService.get_or_create_current_exercise()

    # Historique des clôtures
    closings = ExerciseClosing.objects.filter(
        delete_at__isnull=True
    ).select_related('exercise', 'closed_by', 'new_exercise').order_by('-closed_at')

    # Données pour l'exercice en cours
    income_data = AccountingService.get_income_statement(exercise)

    context = {
        'page_title': "Clôture d'exercice",
        'exercise': exercise,
        'closings': closings,
        'resultat_net': income_data['resultat_net'],
        'total_produits': income_data['total_produits'],
        'total_charges': income_data['total_charges'],
    }
    return render(request, 'core/accounting/exercise_closing.html', context)


@login_required
@module_required('accounting')
def close_exercise_action(request):
    """Action POST pour clôturer l'exercice en cours."""
    from django.contrib import messages

    if request.method != 'POST':
        return redirect('exercise_closing')

    exercise = ExerciseService.get_or_create_current_exercise()

    try:
        closing = AccountingService.close_exercise(exercise, user=request.user)
        new_exercise = AccountingService.open_new_exercise(closing, user=request.user)
        messages.success(
            request,
            f"Exercice clôturé avec succès. Résultat : {closing.result_amount} FCFA. "
            f"Nouvel exercice créé."
        )
    except ValueError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f"Erreur lors de la clôture : {str(e)}")

    return redirect('exercise_closing')
