from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F, Sum, Count, Max
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.utils.translation import gettext as _, pgettext
from django.views.decorators.http import require_POST
from django.http import JsonResponse, Http404
from core.models.sale_models import Sale, SaleProduct, CreditSale
from core.models.user_models import Client, Supplier, CustomUser
from core.models.accounting_models import (
    Daily, DailyExpense, DailyRecipe, ExpenseType, Exercise,
    Account, Payment, RecipeType, SupplierPayment, Invoice,
    TaxRate, BankStatement, ExerciseClosing, PAYMENT_METHOD_CHOICES,
)
from core.models.product_models import Product, Category, Gamme, Rayon, GrammageType
from core.models.inventory_models import Supply, Inventory, InventorySnapshot, DailyInventory, CreditSupply, PaymentSchedule
from core.services.daily_service import DailyService
from core.forms import (
    SupplyForm, ExpenseForm, ClientForm, SupplierForm, InventoryForm,
    DataMigrationForm, PaymentForm, SupplierPaymentForm,
    SaleCancellationForm, SalePartialReturnForm,
    SupplyCancellationForm, SupplyPartialReturnForm,
    SystemSettingsForm, ReferenceDataForm, ProductForm,
    StaffForm, StaffPasswordResetForm, TaxRateForm,
)
from core.services.excercise_service import ExerciseService
from core.services.accounting_service import AccountingService
from core.services.sale_service import SaleService
from core.services.supply_service import SupplyService
from core.decorators import module_required, superuser_required

import csv
import logging
import re

from django.conf import settings as django_settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _safe_next(request, default):
    """Retourne le paramètre ``next`` seulement s'il pointe vers ce site."""
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


_CSV_FORMULA_PREFIX = re.compile(r'^[=+@\t\r]|^-(?!\d)')


class _SafeCsvWriter:
    """
    Enveloppe csv.writer qui neutralise l'injection de formules tableur :
    une cellule commençant par = + @ (ou - suivi d'autre chose qu'un chiffre)
    est préfixée d'une apostrophe. Les nombres négatifs restent des nombres.
    """

    def __init__(self, writer):
        self._writer = writer

    @staticmethod
    def _clean(value):
        if isinstance(value, str) and value and _CSV_FORMULA_PREFIX.match(value):
            return "'" + value
        return value

    def writerow(self, row):
        self._writer.writerow([self._clean(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def _client_ip(request):
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _clean_date_param(request, name, default=''):
    """Paramètre de filtre date : renvoyé tel quel s'il est une date ISO valide, sinon ``default``."""
    raw = (request.GET.get(name) or '').strip()
    if not raw:
        return default
    try:
        return raw if parse_date(raw) else default
    except ValueError:
        return default


def _clean_int_param(request, name, default=''):
    """Paramètre de filtre identifiant : chaîne de chiffres ou ``default``."""
    raw = (request.GET.get(name) or '').strip()
    return raw if raw.isdigit() else default


def _login_ratelimit_keys(request, username):
    ip = _client_ip(request)
    return (
        f"login-fail:ip:{ip}",
        f"login-fail:user:{ip}:{(username or '').lower()[:150]}",
    )


def _login_is_blocked(request, username):
    max_attempts = django_settings.LOGIN_RATELIMIT_ATTEMPTS
    ip_key, user_key = _login_ratelimit_keys(request, username)
    # Par couple (IP, identifiant) : max_attempts ; par IP seule : 4x plus large
    return (
        cache.get(user_key, 0) >= max_attempts
        or cache.get(ip_key, 0) >= max_attempts * 4
    )


def _login_register_failure(request, username):
    window = django_settings.LOGIN_RATELIMIT_WINDOW_SECONDS
    for key in _login_ratelimit_keys(request, username):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)


def _login_reset_failures(request, username):
    cache.delete_many(list(_login_ratelimit_keys(request, username)))



@sensitive_post_parameters('password')
@require_http_methods(['GET', 'POST'])
def login_view(request):
    """Vue de connexion personnalisée (accessible aux non-admins)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    username = ''
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if _login_is_blocked(request, username):
            minutes = max(1, django_settings.LOGIN_RATELIMIT_WINDOW_SECONDS // 60)
            error = _(
                "Trop de tentatives de connexion. Réessayez dans %(minutes)s minute(s)."
            ) % {'minutes': minutes}
        elif username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                _login_reset_failures(request, username)
                auth_login(request, user)
                # ``next`` n'est suivi que s'il reste sur ce site (anti open redirect)
                return redirect(_safe_next(request, '/'))
            else:
                _login_register_failure(request, username)
                error = _("Nom d'utilisateur ou mot de passe incorrect.")
        else:
            error = _("Veuillez remplir tous les champs.")

    return render(request, 'core/login.html', {
        'error': error,
        'username': username,
        'next': _safe_next(request, ''),
    })


@require_POST
def logout_view(request):
    """Déconnexion (POST uniquement : un simple lien/image ne peut plus déconnecter)."""
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
        'page_title': _('Tableau de bord'),
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
        'page_title': _('Statistiques'),
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
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    category_id = _clean_int_param(request, 'category')
    gamme_id = request.GET.get('gamme', '')
    rayon_id = request.GET.get('rayon', '')
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
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
        'labels': [row['category__name'] or _('Sans catégorie') for row in category_rows],
        'counts': [int(row['product_count'] or 0) for row in category_rows],
        'stock': [int(row['stock_units'] or 0) for row in category_rows],
    }

    stock_health_chart = {
        'labels': [_('Disponible'), _('Stock bas'), _('Rupture')],
        'values': [healthy_stock_count, low_stock_count, out_of_stock_count],
    }

    categories = Category.objects.filter(delete_at__isnull=True).order_by('name')
    gammes = Gamme.objects.filter(delete_at__isnull=True).order_by('name')
    rayons = Rayon.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': _('Statistiques produits'),
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
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
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
    client_id = _clean_int_param(request, 'client')
    staff_id = _clean_int_param(request, 'staff')
    sale_type = request.GET.get('type', '')
    payment_status = request.GET.get('status', '')
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
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
        'labels': [_('Payées'), _('Non payées')],
        'values': [paid_sales_count, unpaid_sales_count],
    }

    sale_type_chart = {
        'labels': [_('Comptant'), _('Crédit')],
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
            format_person_label(row['staff__firstname'], row['staff__lastname'], _('Non assigné'))
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
            'label': format_person_label(row['client__firstname'], row['client__lastname'], _('Client comptoir')),
            'total_revenue': row['total_revenue'] or 0,
            'total_sales': row['total_sales'] or 0,
        }
        for row in top_client_rows
    ]

    recent_sales = sales_queryset.order_by('-create_at')[:8]
    clients = Client.objects.filter(delete_at__isnull=True).order_by('firstname', 'lastname')
    staff_members = CustomUser.objects.filter(delete_at__isnull=True, is_active=True).order_by('firstname', 'lastname')

    context = {
        'page_title': _('Statistiques ventes'),
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
def client_statistics(request):
    """Vue détaillée des statistiques clients avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
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
    gender = request.GET.get('gender', '').strip()
    activity = request.GET.get('activity', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    base_clients_queryset = Client.objects.filter(delete_at__isnull=True)
    genders = list(
        base_clients_queryset.exclude(gender__isnull=True).exclude(gender='').values_list('gender', flat=True).distinct().order_by('gender')
    )

    clients_queryset = base_clients_queryset
    if search:
        clients_queryset = clients_queryset.filter(
            Q(firstname__icontains=search)
            | Q(lastname__icontains=search)
            | Q(email__icontains=search)
            | Q(phone_number__icontains=search)
        )
    if gender:
        clients_queryset = clients_queryset.filter(gender=gender)
    if activity == 'active':
        clients_queryset = clients_queryset.filter(sales__delete_at__isnull=True).distinct()
    elif activity == 'inactive':
        clients_queryset = clients_queryset.exclude(sales__delete_at__isnull=True).distinct()
    elif activity == 'debtors':
        clients_queryset = clients_queryset.filter(
            sales__delete_at__isnull=True,
            sales__credit_info__delete_at__isnull=True,
            sales__credit_info__amount_remaining__gt=0,
        ).distinct()

    clients_queryset = clients_queryset.distinct()
    client_ids = list(clients_queryset.values_list('id', flat=True))

    if client_ids:
        sales_queryset = Sale.objects.filter(
            delete_at__isnull=True,
            client_id__in=client_ids,
        ).select_related('client', 'staff')
        credit_sales_queryset = CreditSale.objects.filter(
            delete_at__isnull=True,
            sale__delete_at__isnull=True,
            sale__client_id__in=client_ids,
        ).select_related('sale__client')
        payments_queryset = Payment.objects.filter(
            delete_at__isnull=True,
            credit_sale__delete_at__isnull=True,
            credit_sale__sale__delete_at__isnull=True,
            credit_sale__sale__client_id__in=client_ids,
        ).select_related('credit_sale__sale__client')
        schedules_queryset = PaymentSchedule.objects.filter(
            delete_at__isnull=True,
            schedule_type='CLIENT',
            credit_sale__delete_at__isnull=True,
            credit_sale__sale__delete_at__isnull=True,
            credit_sale__sale__client_id__in=client_ids,
        ).select_related('credit_sale__sale__client')
    else:
        sales_queryset = Sale.objects.none()
        credit_sales_queryset = CreditSale.objects.none()
        payments_queryset = Payment.objects.none()
        schedules_queryset = PaymentSchedule.objects.none()

    if range_start:
        sales_queryset = sales_queryset.filter(create_at__date__gte=range_start)
        payments_queryset = payments_queryset.filter(payment_date__gte=range_start)
        schedules_queryset = schedules_queryset.filter(due_date__gte=range_start)
    if range_end:
        sales_queryset = sales_queryset.filter(create_at__date__lte=range_end)
        payments_queryset = payments_queryset.filter(payment_date__lte=range_end)
        schedules_queryset = schedules_queryset.filter(due_date__lte=range_end)

    clients_created_queryset = clients_queryset
    if range_start:
        clients_created_queryset = clients_created_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        clients_created_queryset = clients_created_queryset.filter(create_at__date__lte=range_end)

    total_clients = clients_queryset.count()
    new_clients_count = clients_created_queryset.count()
    clients_with_sales_count = sales_queryset.values('client_id').distinct().count()
    inactive_clients_count = max(total_clients - clients_with_sales_count, 0)
    clients_with_phone_count = clients_queryset.exclude(phone_number__isnull=True).exclude(phone_number='').count()
    clients_with_email_count = clients_queryset.exclude(email__isnull=True).exclude(email='').count()

    total_revenue = sales_queryset.aggregate(total=Sum('total'))['total'] or 0
    sales_count = sales_queryset.count()
    average_revenue_per_client = (total_revenue / clients_with_sales_count) if clients_with_sales_count else 0
    credit_sales_count = credit_sales_queryset.count()
    credit_clients_count = credit_sales_queryset.values('sale__client_id').distinct().count()
    receivables_total = credit_sales_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    payments_received_total = payments_queryset.aggregate(total=Sum('amount'))['total'] or 0
    overdue_schedules_count = schedules_queryset.exclude(status='PAID').filter(due_date__lt=today).count()

    client_bucket, client_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    new_clients_rows = clients_created_queryset.annotate(bucket=client_bucket).values('bucket').annotate(
        total_clients=Count('id')
    ).order_by('bucket')
    client_growth_chart = {
        'labels': [format_bucket_label(row['bucket'], client_bucket_kind) for row in new_clients_rows],
        'values': [int(row['total_clients'] or 0) for row in new_clients_rows],
    }

    sales_bucket, sales_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    client_sales_rows = sales_queryset.annotate(bucket=sales_bucket).values('bucket').annotate(
        total_revenue=Sum('total'),
        total_sales=Count('id'),
    ).order_by('bucket')
    sales_trend_chart = {
        'labels': [format_bucket_label(row['bucket'], sales_bucket_kind) for row in client_sales_rows],
        'revenue': [float(row['total_revenue'] or 0) for row in client_sales_rows],
        'sales': [int(row['total_sales'] or 0) for row in client_sales_rows],
    }

    gender_rows = list(
        clients_queryset.values('gender').annotate(total_clients=Count('id')).order_by('-total_clients', 'gender')
    )
    gender_distribution_chart = {
        'labels': [row['gender'] or _('Non renseigné') for row in gender_rows],
        'values': [int(row['total_clients'] or 0) for row in gender_rows],
    }

    top_client_rows = list(
        sales_queryset.values('client_id', 'client__firstname', 'client__lastname').annotate(
            total_revenue=Sum('total'),
            total_sales=Count('id'),
        ).order_by('-total_revenue', '-total_sales')[:8]
    )
    outstanding_rows = list(
        credit_sales_queryset.values('sale__client_id').annotate(
            total_outstanding=Sum('amount_remaining'),
            total_credit_sales=Count('id'),
        )
    )
    payment_rows = list(
        payments_queryset.values('credit_sale__sale__client_id').annotate(total_payments=Sum('amount'))
    )
    sales_activity_rows = list(
        sales_queryset.values('client_id').annotate(
            total_sales=Count('id'),
            last_sale_at=Max('create_at'),
        )
    )

    outstanding_map = {
        row['sale__client_id']: {
            'total_outstanding': row['total_outstanding'] or 0,
            'total_credit_sales': int(row['total_credit_sales'] or 0),
        }
        for row in outstanding_rows
    }
    payment_map = {
        row['credit_sale__sale__client_id']: row['total_payments'] or 0
        for row in payment_rows
    }
    sales_activity_map = {
        row['client_id']: {
            'total_sales': int(row['total_sales'] or 0),
            'last_sale_at': row['last_sale_at'],
        }
        for row in sales_activity_rows
    }

    top_clients = []
    for row in top_client_rows:
        client_id = row['client_id']
        debt_data = outstanding_map.get(client_id, {})
        top_clients.append({
            'label': format_person_label(row['client__firstname'], row['client__lastname'], _('Client comptoir')),
            'total_revenue': row['total_revenue'] or 0,
            'total_sales': int(row['total_sales'] or 0),
            'outstanding_total': debt_data.get('total_outstanding', 0),
            'payments_total': payment_map.get(client_id, 0),
            'credit_sales_count': debt_data.get('total_credit_sales', 0),
        })

    top_clients_chart = {
        'labels': [row['label'] for row in top_clients],
        'revenue': [float(row['total_revenue']) for row in top_clients],
        'outstanding': [float(row['outstanding_total']) for row in top_clients],
    }

    recent_clients = []
    for client in clients_queryset.order_by('-create_at', '-id')[:8]:
        activity_data = sales_activity_map.get(client.id, {})
        debt_data = outstanding_map.get(client.id, {})
        has_sales = activity_data.get('total_sales', 0) > 0
        has_debt = debt_data.get('total_outstanding', 0) > 0
        if has_debt:
            status_label = _('Débiteur')
            status_class = 'warning'
        elif has_sales:
            status_label = _('Actif')
            status_class = 'success'
        else:
            status_label = _('Inactif')
            status_class = 'secondary'

        recent_clients.append({
            'label': client.get_full_name() or _('Client #%(id)s') % {'id': client.id},
            'phone_number': client.phone_number or '-',
            'email': client.email or '-',
            'gender': client.gender or _('Non renseigné'),
            'create_at': client.create_at,
            'last_sale_at': activity_data.get('last_sale_at'),
            'total_sales': activity_data.get('total_sales', 0),
            'outstanding_total': debt_data.get('total_outstanding', 0),
            'status_label': status_label,
            'status_class': status_class,
        })

    context = {
        'page_title': _('Statistiques clients'),
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'genders': genders,
        'current_period': period,
        'current_search': search,
        'current_gender': gender,
        'current_activity': activity,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_clients': total_clients,
        'new_clients_count': new_clients_count,
        'clients_with_sales_count': clients_with_sales_count,
        'inactive_clients_count': inactive_clients_count,
        'clients_with_phone_count': clients_with_phone_count,
        'clients_with_email_count': clients_with_email_count,
        'sales_count': sales_count,
        'total_revenue': total_revenue,
        'average_revenue_per_client': average_revenue_per_client,
        'credit_sales_count': credit_sales_count,
        'credit_clients_count': credit_clients_count,
        'receivables_total': receivables_total,
        'payments_received_total': payments_received_total,
        'overdue_schedules_count': overdue_schedules_count,
        'client_growth_chart': client_growth_chart,
        'sales_trend_chart': sales_trend_chart,
        'gender_distribution_chart': gender_distribution_chart,
        'top_clients_chart': top_clients_chart,
        'top_clients': top_clients,
        'recent_clients': recent_clients,
    }
    return render(request, 'core/statistics_clients.html', context)


@login_required
@module_required('dashboard')
def supplier_statistics(request):
    """Vue détaillée des statistiques fournisseurs avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()
    payment_method_labels = dict(SupplierPayment._meta.get_field('payment_method').choices)

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    activity = request.GET.get('activity', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    suppliers_queryset = Supplier.objects.filter(delete_at__isnull=True)
    if search:
        suppliers_queryset = suppliers_queryset.filter(
            Q(name__icontains=search)
            | Q(contact_phone__icontains=search)
            | Q(contact_email__icontains=search)
            | Q(niu__icontains=search)
            | Q(address__icontains=search)
        )
    if activity == 'active':
        suppliers_queryset = suppliers_queryset.filter(
            supplies__isnull=False,
            supplies__delete_at__isnull=True,
        ).distinct()
    elif activity == 'inactive':
        suppliers_queryset = suppliers_queryset.exclude(
            supplies__isnull=False,
            supplies__delete_at__isnull=True,
        ).distinct()
    elif activity == 'debtors':
        suppliers_queryset = suppliers_queryset.filter(
            supplies__isnull=False,
            supplies__delete_at__isnull=True,
            supplies__credit_info__delete_at__isnull=True,
            supplies__credit_info__amount_remaining__gt=0,
        ).distinct()

    suppliers_queryset = suppliers_queryset.distinct()
    supplier_ids = list(suppliers_queryset.values_list('id', flat=True))

    if supplier_ids:
        supplies_queryset = Supply.objects.filter(
            delete_at__isnull=True,
            supplier_id__in=supplier_ids,
        ).select_related('supplier', 'product', 'staff', 'credit_info')
        credit_supplies_queryset = CreditSupply.objects.filter(
            delete_at__isnull=True,
            supply__delete_at__isnull=True,
            supply__supplier_id__in=supplier_ids,
        ).select_related('supply__supplier')
        payments_queryset = SupplierPayment.objects.filter(
            delete_at__isnull=True,
            supplier_id__in=supplier_ids,
        ).select_related('supplier', 'supply')
        schedules_queryset = PaymentSchedule.objects.filter(
            delete_at__isnull=True,
            schedule_type='SUPPLIER',
            credit_supply__delete_at__isnull=True,
            credit_supply__supply__delete_at__isnull=True,
            credit_supply__supply__supplier_id__in=supplier_ids,
        ).select_related('credit_supply__supply__supplier')
    else:
        supplies_queryset = Supply.objects.none()
        credit_supplies_queryset = CreditSupply.objects.none()
        payments_queryset = SupplierPayment.objects.none()
        schedules_queryset = PaymentSchedule.objects.none()

    if range_start:
        supplies_queryset = supplies_queryset.filter(create_at__date__gte=range_start)
        payments_queryset = payments_queryset.filter(payment_date__gte=range_start)
        schedules_queryset = schedules_queryset.filter(due_date__gte=range_start)
    if range_end:
        supplies_queryset = supplies_queryset.filter(create_at__date__lte=range_end)
        payments_queryset = payments_queryset.filter(payment_date__lte=range_end)
        schedules_queryset = schedules_queryset.filter(due_date__lte=range_end)

    suppliers_created_queryset = suppliers_queryset
    if range_start:
        suppliers_created_queryset = suppliers_created_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        suppliers_created_queryset = suppliers_created_queryset.filter(create_at__date__lte=range_end)

    total_suppliers = suppliers_queryset.count()
    new_suppliers_count = suppliers_created_queryset.count()
    suppliers_with_supplies_count = supplies_queryset.values('supplier_id').distinct().count()
    inactive_suppliers_count = max(total_suppliers - suppliers_with_supplies_count, 0)
    suppliers_with_phone_count = suppliers_queryset.exclude(contact_phone__isnull=True).exclude(contact_phone='').count()
    suppliers_with_email_count = suppliers_queryset.exclude(contact_email__isnull=True).exclude(contact_email='').count()

    total_supplies_amount = supplies_queryset.aggregate(total=Sum('total_price'))['total'] or 0
    supplies_count = supplies_queryset.count()
    average_supply_per_supplier = (total_supplies_amount / suppliers_with_supplies_count) if suppliers_with_supplies_count else 0
    credit_supplies_count = credit_supplies_queryset.count()
    creditor_suppliers_count = credit_supplies_queryset.values('supply__supplier_id').distinct().count()
    supplier_debt_total = credit_supplies_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    supplier_payments_total = payments_queryset.aggregate(total=Sum('amount'))['total'] or 0
    overdue_schedules_count = schedules_queryset.exclude(status='PAID').filter(due_date__lt=today).count()

    supplier_bucket, supplier_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    new_suppliers_rows = suppliers_created_queryset.annotate(bucket=supplier_bucket).values('bucket').annotate(
        total_suppliers=Count('id')
    ).order_by('bucket')
    supplier_growth_chart = {
        'labels': [format_bucket_label(row['bucket'], supplier_bucket_kind) for row in new_suppliers_rows],
        'values': [int(row['total_suppliers'] or 0) for row in new_suppliers_rows],
    }

    supplies_bucket, supplies_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    supplies_rows = supplies_queryset.annotate(bucket=supplies_bucket).values('bucket').annotate(
        total_amount=Sum('total_price'),
        total_supplies=Count('id'),
    ).order_by('bucket')
    supplies_trend_chart = {
        'labels': [format_bucket_label(row['bucket'], supplies_bucket_kind) for row in supplies_rows],
        'amounts': [float(row['total_amount'] or 0) for row in supplies_rows],
        'supplies': [int(row['total_supplies'] or 0) for row in supplies_rows],
    }

    payment_method_rows = list(
        payments_queryset.values('payment_method').annotate(
            total_amount=Sum('amount'),
            total_payments=Count('id'),
        ).order_by('-total_amount', 'payment_method')
    )
    payment_methods_chart = {
        'labels': [payment_method_labels.get(row['payment_method'], row['payment_method']) for row in payment_method_rows],
        'values': [float(row['total_amount'] or 0) for row in payment_method_rows],
    }

    top_supplier_rows = list(
        supplies_queryset.values('supplier_id', 'supplier__name').annotate(
            total_amount=Sum('total_price'),
            total_supplies=Count('id'),
        ).order_by('-total_amount', '-total_supplies')[:8]
    )
    outstanding_rows = list(
        credit_supplies_queryset.values('supply__supplier_id').annotate(
            total_outstanding=Sum('amount_remaining'),
            total_credit_supplies=Count('id'),
        )
    )
    payment_rows = list(
        payments_queryset.values('supplier_id').annotate(total_payments=Sum('amount'))
    )
    supplies_activity_rows = list(
        supplies_queryset.values('supplier_id').annotate(
            total_supplies=Count('id'),
            last_supply_at=Max('create_at'),
        )
    )
    overdue_rows = list(
        schedules_queryset.exclude(status='PAID').values('credit_supply__supply__supplier_id').annotate(
            total_overdue=Count('id')
        )
    )

    outstanding_map = {
        row['supply__supplier_id']: {
            'total_outstanding': row['total_outstanding'] or 0,
            'total_credit_supplies': int(row['total_credit_supplies'] or 0),
        }
        for row in outstanding_rows
    }
    payment_map = {
        row['supplier_id']: row['total_payments'] or 0
        for row in payment_rows
    }
    supplies_activity_map = {
        row['supplier_id']: {
            'total_supplies': int(row['total_supplies'] or 0),
            'last_supply_at': row['last_supply_at'],
        }
        for row in supplies_activity_rows
    }
    overdue_map = {
        row['credit_supply__supply__supplier_id']: int(row['total_overdue'] or 0)
        for row in overdue_rows
    }

    top_suppliers = []
    for row in top_supplier_rows:
        supplier_id = row['supplier_id']
        debt_data = outstanding_map.get(supplier_id, {})
        top_suppliers.append({
            'label': row['supplier__name'] or _('Fournisseur #%(id)s') % {'id': supplier_id},
            'total_amount': row['total_amount'] or 0,
            'total_supplies': int(row['total_supplies'] or 0),
            'outstanding_total': debt_data.get('total_outstanding', 0),
            'payments_total': payment_map.get(supplier_id, 0),
            'credit_supplies_count': debt_data.get('total_credit_supplies', 0),
            'overdue_count': overdue_map.get(supplier_id, 0),
        })

    top_suppliers_chart = {
        'labels': [row['label'] for row in top_suppliers],
        'amounts': [float(row['total_amount']) for row in top_suppliers],
        'outstanding': [float(row['outstanding_total']) for row in top_suppliers],
    }

    recent_suppliers = []
    for supplier in suppliers_queryset.order_by('-create_at', '-id')[:8]:
        activity_data = supplies_activity_map.get(supplier.id, {})
        debt_data = outstanding_map.get(supplier.id, {})
        has_supplies = activity_data.get('total_supplies', 0) > 0
        has_debt = debt_data.get('total_outstanding', 0) > 0
        if has_debt:
            status_label = _('À régler')
            status_class = 'warning'
        elif has_supplies:
            status_label = _('Actif')
            status_class = 'success'
        else:
            status_label = _('Inactif')
            status_class = 'secondary'

        recent_suppliers.append({
            'label': supplier.name or _('Fournisseur #%(id)s') % {'id': supplier.id},
            'phone_number': supplier.contact_phone or '-',
            'email': supplier.contact_email or '-',
            'niu': supplier.niu or '-',
            'create_at': supplier.create_at,
            'last_supply_at': activity_data.get('last_supply_at'),
            'total_supplies': activity_data.get('total_supplies', 0),
            'outstanding_total': debt_data.get('total_outstanding', 0),
            'overdue_count': overdue_map.get(supplier.id, 0),
            'status_label': status_label,
            'status_class': status_class,
        })

    context = {
        'page_title': _('Statistiques fournisseurs'),
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'current_period': period,
        'current_search': search,
        'current_activity': activity,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_suppliers': total_suppliers,
        'new_suppliers_count': new_suppliers_count,
        'suppliers_with_supplies_count': suppliers_with_supplies_count,
        'inactive_suppliers_count': inactive_suppliers_count,
        'suppliers_with_phone_count': suppliers_with_phone_count,
        'suppliers_with_email_count': suppliers_with_email_count,
        'supplies_count': supplies_count,
        'total_supplies_amount': total_supplies_amount,
        'average_supply_per_supplier': average_supply_per_supplier,
        'credit_supplies_count': credit_supplies_count,
        'creditor_suppliers_count': creditor_suppliers_count,
        'supplier_debt_total': supplier_debt_total,
        'supplier_payments_total': supplier_payments_total,
        'overdue_schedules_count': overdue_schedules_count,
        'supplier_growth_chart': supplier_growth_chart,
        'supplies_trend_chart': supplies_trend_chart,
        'payment_methods_chart': payment_methods_chart,
        'top_suppliers_chart': top_suppliers_chart,
        'top_suppliers': top_suppliers,
        'recent_suppliers': recent_suppliers,
    }
    return render(request, 'core/statistics_suppliers.html', context)


@login_required
@module_required('dashboard')
def supply_statistics(request):
    """Vue détaillée des statistiques approvisionnements avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    def format_person_label(firstname, lastname, username):
        full_name = f"{firstname or ''} {lastname or ''}".strip()
        return full_name or username or _('Non assigné')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    supplier_id = _clean_int_param(request, 'supplier')
    staff_id = _clean_int_param(request, 'staff')
    supply_type = request.GET.get('type', '').strip()
    payment_status = request.GET.get('status', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    suppliers = Supplier.objects.filter(delete_at__isnull=True).order_by('name')
    staff_members = CustomUser.objects.filter(delete_at__isnull=True).order_by('firstname', 'lastname', 'username')

    supplies_queryset = Supply.objects.filter(
        delete_at__isnull=True,
    ).select_related('supplier', 'product', 'staff', 'credit_info')

    if search:
        supplies_queryset = supplies_queryset.filter(
            Q(product__name__icontains=search)
            | Q(product__code__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(staff__firstname__icontains=search)
            | Q(staff__lastname__icontains=search)
            | Q(staff__username__icontains=search)
        )
    if supplier_id:
        supplies_queryset = supplies_queryset.filter(supplier_id=supplier_id)
    if staff_id:
        supplies_queryset = supplies_queryset.filter(staff_id=staff_id)
    if supply_type == 'cash':
        supplies_queryset = supplies_queryset.filter(is_credit=False)
    elif supply_type == 'credit':
        supplies_queryset = supplies_queryset.filter(is_credit=True)
    if payment_status == 'paid':
        supplies_queryset = supplies_queryset.filter(is_paid=True)
    elif payment_status == 'unpaid':
        supplies_queryset = supplies_queryset.filter(is_paid=False)
    if range_start:
        supplies_queryset = supplies_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        supplies_queryset = supplies_queryset.filter(create_at__date__lte=range_end)

    supplies_queryset = supplies_queryset.order_by('-create_at', '-id')
    supply_ids = list(supplies_queryset.values_list('id', flat=True))

    if supply_ids:
        credit_supplies_queryset = CreditSupply.objects.filter(
            delete_at__isnull=True,
            supply__delete_at__isnull=True,
            supply_id__in=supply_ids,
        ).select_related('supply__supplier', 'supply__product')
        schedules_queryset = PaymentSchedule.objects.filter(
            delete_at__isnull=True,
            schedule_type='SUPPLIER',
            credit_supply__delete_at__isnull=True,
            credit_supply__supply__delete_at__isnull=True,
            credit_supply__supply_id__in=supply_ids,
        ).select_related('credit_supply__supply__supplier')
    else:
        credit_supplies_queryset = CreditSupply.objects.none()
        schedules_queryset = PaymentSchedule.objects.none()

    supplies_count = supplies_queryset.count()
    total_supplies_amount = supplies_queryset.aggregate(total=Sum('total_price'))['total'] or 0
    total_quantity = supplies_queryset.aggregate(total=Sum('quantity'))['total'] or 0
    average_supply_amount = (total_supplies_amount / supplies_count) if supplies_count else 0
    suppliers_count = supplies_queryset.exclude(supplier__isnull=True).values('supplier_id').distinct().count()
    products_count = supplies_queryset.values('product_id').distinct().count()
    staff_count = supplies_queryset.exclude(staff__isnull=True).values('staff_id').distinct().count()
    credit_supplies_count = supplies_queryset.filter(is_credit=True).count()
    cash_supplies_count = max(supplies_count - credit_supplies_count, 0)
    paid_supplies_count = supplies_queryset.filter(is_paid=True).count()
    unpaid_supplies_count = supplies_queryset.filter(is_paid=False).count()
    paid_supplies_amount = supplies_queryset.filter(is_paid=True).aggregate(total=Sum('total_price'))['total'] or 0
    unpaid_supplies_amount = supplies_queryset.filter(is_paid=False).aggregate(total=Sum('total_price'))['total'] or 0
    outstanding_total = credit_supplies_queryset.aggregate(total=Sum('amount_remaining'))['total'] or 0
    overdue_schedules_count = schedules_queryset.exclude(status='PAID').filter(due_date__lt=today).count()

    supplies_bucket, supplies_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    supplies_rows = supplies_queryset.annotate(bucket=supplies_bucket).values('bucket').annotate(
        total_amount=Sum('total_price'),
        total_quantity=Sum('quantity'),
        total_supplies=Count('id'),
    ).order_by('bucket')
    supplies_trend_chart = {
        'labels': [format_bucket_label(row['bucket'], supplies_bucket_kind) for row in supplies_rows],
        'amounts': [float(row['total_amount'] or 0) for row in supplies_rows],
        'quantities': [int(row['total_quantity'] or 0) for row in supplies_rows],
        'supplies': [int(row['total_supplies'] or 0) for row in supplies_rows],
    }

    payment_status_chart = {
        'labels': [_('Payés'), _('Non payés')],
        'values': [paid_supplies_count, unpaid_supplies_count],
    }

    supply_type_chart = {
        'labels': [_('Comptant'), _('Crédit')],
        'values': [cash_supplies_count, credit_supplies_count],
    }

    top_product_rows = list(
        supplies_queryset.values(
            'product_id',
            'product__code',
            'product__name',
        ).annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('total_price'),
            total_supplies=Count('id'),
            total_suppliers=Count('supplier_id', distinct=True),
        ).order_by('-total_amount', '-total_quantity', 'product__name')[:8]
    )
    top_products_chart = {
        'labels': [row['product__name'] or _("Produit #%(id)s") % {'id': row['product_id']} for row in top_product_rows],
        'amounts': [float(row['total_amount'] or 0) for row in top_product_rows],
        'quantities': [int(row['total_quantity'] or 0) for row in top_product_rows],
    }

    top_supplier_rows = list(
        supplies_queryset.values('supplier_id', 'supplier__name').annotate(
            total_amount=Sum('total_price'),
            total_quantity=Sum('quantity'),
            total_supplies=Count('id'),
        ).order_by('-total_amount', '-total_quantity', 'supplier__name')[:8]
    )
    outstanding_rows = list(
        credit_supplies_queryset.values('supply__supplier_id').annotate(
            total_outstanding=Sum('amount_remaining'),
        )
    )
    outstanding_map = {
        row['supply__supplier_id']: row['total_outstanding'] or 0
        for row in outstanding_rows
    }

    top_suppliers = []
    for row in top_supplier_rows:
        supplier_key = row['supplier_id']
        top_suppliers.append({
            'label': row['supplier__name'] or _('Sans fournisseur'),
            'total_supplies': int(row['total_supplies'] or 0),
            'total_quantity': int(row['total_quantity'] or 0),
            'total_amount': row['total_amount'] or 0,
            'outstanding_total': outstanding_map.get(supplier_key, 0),
        })

    recent_supplies = list(supplies_queryset[:8])

    context = {
        'page_title': _('Statistiques approvisionnements'),
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'suppliers': suppliers,
        'staff_members': staff_members,
        'current_period': period,
        'current_search': search,
        'current_supplier': supplier_id,
        'current_staff': staff_id,
        'current_type': supply_type,
        'current_status': payment_status,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'supplies_count': supplies_count,
        'total_supplies_amount': total_supplies_amount,
        'total_quantity': total_quantity,
        'average_supply_amount': average_supply_amount,
        'suppliers_count': suppliers_count,
        'products_count': products_count,
        'staff_count': staff_count,
        'credit_supplies_count': credit_supplies_count,
        'cash_supplies_count': cash_supplies_count,
        'paid_supplies_count': paid_supplies_count,
        'unpaid_supplies_count': unpaid_supplies_count,
        'paid_supplies_amount': paid_supplies_amount,
        'unpaid_supplies_amount': unpaid_supplies_amount,
        'outstanding_total': outstanding_total,
        'overdue_schedules_count': overdue_schedules_count,
        'supplies_trend_chart': supplies_trend_chart,
        'payment_status_chart': payment_status_chart,
        'supply_type_chart': supply_type_chart,
        'top_products_chart': top_products_chart,
        'top_products': top_product_rows,
        'top_suppliers': top_suppliers,
        'recent_supplies': recent_supplies,
        'format_person_label': format_person_label,
    }
    return render(request, 'core/statistics_supplies.html', context)


@login_required
@module_required('dashboard')
def expense_statistics(request):
    """Vue détaillée des statistiques dépenses et recettes avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings

    def format_period_label(start, end):
        if start and end:
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    def format_person_label(firstname, lastname, username):
        full_name = f"{firstname or ''} {lastname or ''}".strip()
        return full_name or username or _('Non assigné')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    staff_id = _clean_int_param(request, 'staff')
    expense_type_id = _clean_int_param(request, 'expense_type')
    recipe_type_id = request.GET.get('recipe_type', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
        range_start = parsed_date_from
        range_end = parsed_date_to
    else:
        period_name, days_back = period_options[period]
        range_end = today
        range_start = today - timedelta(days=days_back)

    staff_members = CustomUser.objects.filter(delete_at__isnull=True).order_by('firstname', 'lastname', 'username')
    expense_types = ExpenseType.objects.filter(delete_at__isnull=True).order_by('name')
    recipe_types = RecipeType.objects.filter(delete_at__isnull=True).order_by('name')

    expenses_queryset = DailyExpense.objects.filter(
        delete_at__isnull=True,
    ).select_related('expense_type', 'staff', 'daily', 'exercise', 'account')
    recipes_queryset = DailyRecipe.objects.filter(
        delete_at__isnull=True,
    ).select_related('recipe_type', 'staff', 'daily', 'exercise', 'account')

    if search:
        expenses_queryset = expenses_queryset.filter(
            Q(description__icontains=search)
            | Q(expense_type__name__icontains=search)
            | Q(staff__firstname__icontains=search)
            | Q(staff__lastname__icontains=search)
            | Q(staff__username__icontains=search)
            | Q(account__code__icontains=search)
        )
        recipes_queryset = recipes_queryset.filter(
            Q(description__icontains=search)
            | Q(recipe_type__name__icontains=search)
            | Q(staff__firstname__icontains=search)
            | Q(staff__lastname__icontains=search)
            | Q(staff__username__icontains=search)
            | Q(account__code__icontains=search)
        )
    if staff_id:
        expenses_queryset = expenses_queryset.filter(staff_id=staff_id)
        recipes_queryset = recipes_queryset.filter(staff_id=staff_id)
    if expense_type_id:
        expenses_queryset = expenses_queryset.filter(expense_type_id=expense_type_id)
    if recipe_type_id:
        recipes_queryset = recipes_queryset.filter(recipe_type_id=recipe_type_id)
    if range_start:
        expenses_queryset = expenses_queryset.filter(create_at__date__gte=range_start)
        recipes_queryset = recipes_queryset.filter(create_at__date__gte=range_start)
    if range_end:
        expenses_queryset = expenses_queryset.filter(create_at__date__lte=range_end)
        recipes_queryset = recipes_queryset.filter(create_at__date__lte=range_end)

    expenses_queryset = expenses_queryset.order_by('-create_at', '-id')
    recipes_queryset = recipes_queryset.order_by('-create_at', '-id')

    expenses_count = expenses_queryset.count()
    recipes_count = recipes_queryset.count()
    operations_count = expenses_count + recipes_count
    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or 0
    total_recipes = recipes_queryset.aggregate(total=Sum('amount'))['total'] or 0
    net_result = total_recipes - total_expenses
    average_expense_amount = total_expenses / expenses_count if expenses_count else 0
    average_recipe_amount = total_recipes / recipes_count if recipes_count else 0
    expense_types_count = expenses_queryset.exclude(expense_type__isnull=True).values('expense_type_id').distinct().count()
    recipe_types_count = recipes_queryset.exclude(recipe_type__isnull=True).values('recipe_type_id').distinct().count()
    staff_ids = set(expenses_queryset.exclude(staff__isnull=True).values_list('staff_id', flat=True))
    staff_ids.update(recipes_queryset.exclude(staff__isnull=True).values_list('staff_id', flat=True))
    staff_count = len(staff_ids)

    flow_bucket, flow_bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    expense_rows = expenses_queryset.annotate(bucket=flow_bucket).values('bucket').annotate(
        total_amount=Sum('amount'),
        total_operations=Count('id'),
    ).order_by('bucket')
    recipe_rows = recipes_queryset.annotate(bucket=flow_bucket).values('bucket').annotate(
        total_amount=Sum('amount'),
        total_operations=Count('id'),
    ).order_by('bucket')

    bucket_map = {}
    for row in expense_rows:
        bucket_map[row['bucket']] = {
            'expenses': float(row['total_amount'] or 0),
            'recipes': 0.0,
            'operations': int(row['total_operations'] or 0),
        }
    for row in recipe_rows:
        bucket_data = bucket_map.setdefault(row['bucket'], {
            'expenses': 0.0,
            'recipes': 0.0,
            'operations': 0,
        })
        bucket_data['recipes'] = float(row['total_amount'] or 0)
        bucket_data['operations'] += int(row['total_operations'] or 0)

    ordered_buckets = sorted(bucket_map.keys())
    financial_trend_chart = {
        'labels': [format_bucket_label(bucket, flow_bucket_kind) for bucket in ordered_buckets],
        'expenses': [bucket_map[bucket]['expenses'] for bucket in ordered_buckets],
        'recipes': [bucket_map[bucket]['recipes'] for bucket in ordered_buckets],
        'net': [bucket_map[bucket]['recipes'] - bucket_map[bucket]['expenses'] for bucket in ordered_buckets],
        'operations': [bucket_map[bucket]['operations'] for bucket in ordered_buckets],
    }

    top_expense_types = [
        {
            'label': row['expense_type__name'] or _('Sans type'),
            'total_amount': row['total_amount'] or 0,
            'total_operations': int(row['total_operations'] or 0),
        }
        for row in expenses_queryset.values('expense_type__name').annotate(
            total_amount=Sum('amount'),
            total_operations=Count('id'),
        ).order_by('-total_amount', '-total_operations', 'expense_type__name')[:8]
    ]
    top_recipe_types = [
        {
            'label': row['recipe_type__name'] or _('Sans type'),
            'total_amount': row['total_amount'] or 0,
            'total_operations': int(row['total_operations'] or 0),
        }
        for row in recipes_queryset.values('recipe_type__name').annotate(
            total_amount=Sum('amount'),
            total_operations=Count('id'),
        ).order_by('-total_amount', '-total_operations', 'recipe_type__name')[:8]
    ]

    expense_types_chart = {
        'labels': [row['label'] for row in top_expense_types],
        'values': [float(row['total_amount'] or 0) for row in top_expense_types],
    }
    recipe_types_chart = {
        'labels': [row['label'] for row in top_recipe_types],
        'values': [float(row['total_amount'] or 0) for row in top_recipe_types],
    }

    staff_map = {}
    for row in expenses_queryset.values(
        'staff_id', 'staff__firstname', 'staff__lastname', 'staff__username',
    ).annotate(total_amount=Sum('amount'), total_operations=Count('id')):
        staff_key = row['staff_id'] if row['staff_id'] is not None else 'unassigned'
        staff_map[staff_key] = {
            'label': format_person_label(row['staff__firstname'], row['staff__lastname'], row['staff__username']),
            'expense_total': row['total_amount'] or 0,
            'recipe_total': 0,
            'operations': int(row['total_operations'] or 0),
        }
    for row in recipes_queryset.values(
        'staff_id', 'staff__firstname', 'staff__lastname', 'staff__username',
    ).annotate(total_amount=Sum('amount'), total_operations=Count('id')):
        staff_key = row['staff_id'] if row['staff_id'] is not None else 'unassigned'
        staff_entry = staff_map.setdefault(staff_key, {
            'label': format_person_label(row['staff__firstname'], row['staff__lastname'], row['staff__username']),
            'expense_total': 0,
            'recipe_total': 0,
            'operations': 0,
        })
        staff_entry['recipe_total'] = row['total_amount'] or 0
        staff_entry['operations'] += int(row['total_operations'] or 0)

    top_staff = sorted(
        [
            {
                **row,
                'total_flow': (row['expense_total'] or 0) + (row['recipe_total'] or 0),
            }
            for row in staff_map.values()
        ],
        key=lambda row: (row['total_flow'], row['recipe_total'], row['expense_total'], row['operations']),
        reverse=True,
    )[:8]
    staff_balance_chart = {
        'labels': [row['label'] for row in top_staff],
        'expenses': [float(row['expense_total'] or 0) for row in top_staff],
        'recipes': [float(row['recipe_total'] or 0) for row in top_staff],
    }

    recent_operations = []
    for expense in expenses_queryset[:6]:
        recent_operations.append({
            'kind': 'expense',
            'kind_label': _('Dépense'),
            'type_label': expense.expense_type.name if expense.expense_type else _('Sans type'),
            'description': expense.description or '-',
            'staff_label': format_person_label(
                getattr(expense.staff, 'firstname', None),
                getattr(expense.staff, 'lastname', None),
                getattr(expense.staff, 'username', None),
            ),
            'date': expense.create_at,
            'amount': expense.amount,
        })
    for recipe in recipes_queryset[:6]:
        recent_operations.append({
            'kind': 'recipe',
            'kind_label': _('Recette'),
            'type_label': recipe.recipe_type.name if recipe.recipe_type else _('Sans type'),
            'description': recipe.description or '-',
            'staff_label': format_person_label(
                getattr(recipe.staff, 'firstname', None),
                getattr(recipe.staff, 'lastname', None),
                getattr(recipe.staff, 'username', None),
            ),
            'date': recipe.create_at,
            'amount': recipe.amount,
        })
    recent_operations.sort(key=lambda row: row['date'] or timezone.now(), reverse=True)
    recent_operations = recent_operations[:10]

    context = {
        'page_title': _('Statistiques dépenses & recettes'),
        'currency': settings_obj.currency_symbol,
        'generated_at': timezone.now(),
        'period_name': period_name,
        'period_label': format_period_label(range_start, range_end),
        'staff_members': staff_members,
        'expense_types': expense_types,
        'recipe_types': recipe_types,
        'current_period': period,
        'current_search': search,
        'current_staff': staff_id,
        'current_expense_type': expense_type_id,
        'current_recipe_type': recipe_type_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'expenses_count': expenses_count,
        'recipes_count': recipes_count,
        'operations_count': operations_count,
        'total_expenses': total_expenses,
        'total_recipes': total_recipes,
        'net_result': net_result,
        'average_expense_amount': average_expense_amount,
        'average_recipe_amount': average_recipe_amount,
        'expense_types_count': expense_types_count,
        'recipe_types_count': recipe_types_count,
        'staff_count': staff_count,
        'financial_trend_chart': financial_trend_chart,
        'expense_types_chart': expense_types_chart,
        'recipe_types_chart': recipe_types_chart,
        'staff_balance_chart': staff_balance_chart,
        'top_expense_types': top_expense_types,
        'top_recipe_types': top_recipe_types,
        'top_staff': top_staff,
        'recent_operations': recent_operations,
    }
    return render(request, 'core/statistics_expenses.html', context)


@login_required
@module_required('dashboard')
def personnel_statistics(request):
    """Vue détaillée des statistiques personnel avec filtres et graphiques."""
    from core.models.settings_models import SystemSettings, AppModule

    def format_period_label(start, end):
        if start and end:
            return _("Du %(start)s au %(end)s") % {
                'start': start.strftime('%d/%m/%Y'),
                'end': end.strftime('%d/%m/%Y'),
            }
        if start:
            return _("Depuis le %(start)s") % {'start': start.strftime('%d/%m/%Y')}
        if end:
            return _("Jusqu'au %(end)s") % {'end': end.strftime('%d/%m/%Y')}
        return _("Toutes les données disponibles")

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
            return date_format(bucket_date, 'M Y')
        if bucket_kind == 'week':
            week_end = bucket_date + timedelta(days=6)
            return f"{bucket_date.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        return bucket_date.strftime('%d/%m')

    def format_person_label(firstname, lastname, username):
        full_name = f"{firstname or ''} {lastname or ''}".strip()
        return full_name or username or _('Utilisateur')

    settings_obj = SystemSettings.get_settings()
    today = timezone.localdate()

    period = request.GET.get('period', '30d')
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '')
    role = request.GET.get('role', '').strip()
    gender = request.GET.get('gender', '').strip()
    module_code = request.GET.get('module', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from
        date_from = parsed_date_from.isoformat()
        date_to = parsed_date_to.isoformat()

    period_options = {
        '7d': (_('7 derniers jours'), 6),
        '30d': (_('30 derniers jours'), 29),
        '90d': (_('90 derniers jours'), 89),
        '365d': (_('12 derniers mois'), 364),
    }

    if date_from or date_to:
        period = 'custom'
    elif period not in period_options:
        period = '30d'

    if period == 'custom':
        period_name = _('Période personnalisée')
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
        'labels': [_('Actifs'), _('Inactifs')],
        'values': [active_staff_count, inactive_staff_count],
    }

    role_rows = list(
        staff_queryset.values('role').annotate(total_users=Count('id')).order_by('-total_users', 'role')[:8]
    )
    role_distribution_chart = {
        'labels': [row['role'] or _('Non renseigné') for row in role_rows],
        'values': [int(row['total_users'] or 0) for row in role_rows],
    }

    sales_bucket, bucket_kind = chart_bucket_for_range('create_at', range_start, range_end)
    supplies_bucket, _unused = chart_bucket_for_range('create_at', range_start, range_end)
    inventories_bucket, _unused = chart_bucket_for_range('create_at', range_start, range_end)
    daily_bucket, _unused = chart_bucket_for_range('create_at', range_start, range_end)

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
            'role': member.role or _('Non renseigné'),
            'status_label': _('Actif') if member.is_active else _('Inactif'),
            'sales_count': sales_total,
            'supply_count': supply_count,
            'stock_actions': stock_count,
            'total_actions': total_actions,
            'total_revenue': sales_data.get('total_revenue', 0),
            'module_count': len(active_modules),
            'modules_label': ', '.join(active_modules) or _('Aucun module'),
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
            'role': member.role or _('Non renseigné'),
            'gender': member.gender or _('Non renseigné'),
            'status_label': _('Actif') if member.is_active else _('Inactif'),
            'status_class': 'success' if member.is_active else 'warning',
            'modules_label': ', '.join(active_modules) or _('Aucun module'),
            'date_joined': member.date_joined,
        })

    context = {
        'page_title': _('Statistiques personnel'),
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
                sale__delete_at__isnull=True,
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
        'page_title': _('Ventes'),
        'sales': sales_list,
        'sale_products': sale_products_list,
        'clients': clients_list,
        'client_form': ClientForm(),
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
    client_id = _clean_int_param(request, 'client')
    staff_id = _clean_int_param(request, 'staff')
    sale_type = request.GET.get('type', '')
    payment_status = request.GET.get('status', '')
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')
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
            queryset = queryset.filter(sale__delete_at__isnull=True, sale__is_paid=True)
        elif payment_status == 'unpaid':
            queryset = queryset.filter(sale__delete_at__isnull=True, sale__is_paid=False)
        elif payment_status == 'cancelled':
            queryset = queryset.filter(sale__delete_at__isnull=False)

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
            'page_title': _('Historique des ventes - Produits'),
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
            'current_full_path': request.get_full_path(),
            'payment_method_choices': PAYMENT_METHOD_CHOICES,
            'total_count': paginator.count,
            'total_sales_amount': total_products_amount,
        }
        return render(request, 'core/sales_history.html', context)

    # Mode ventes par défaut (existing code)
    queryset = Sale.objects.select_related('client', 'staff', 'daily', 'credit_info').prefetch_related(
        'sale_products__product',
        'sale_returns',
    )

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
        queryset = queryset.filter(delete_at__isnull=True, is_paid=True)
    elif payment_status == 'unpaid':
        queryset = queryset.filter(delete_at__isnull=True, is_paid=False)
    elif payment_status == 'cancelled':
        queryset = queryset.filter(delete_at__isnull=False)

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
        'page_title': _('Historique des ventes'),
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
        'current_full_path': request.get_full_path(),
        'payment_method_choices': PAYMENT_METHOD_CHOICES,
        'total_count': paginator.count,
        'total_sales_amount': total_sales_amount,
    }
    return render(request, 'core/sales_history.html', context)


@login_required
@module_required('sales')
@require_POST
def cancel_sale(request, sale_id):
    """Annulation totale d'une vente depuis l'historique."""
    sale = get_object_or_404(
        Sale.objects.select_related('client', 'staff', 'daily', 'daily__exercise', 'credit_info'),
        id=sale_id,
    )
    form = SaleCancellationForm(request.POST, sale=sale)
    redirect_to = _safe_next(request, 'sales_history')

    if form.is_valid():
        try:
            refund_amount = SaleService.cancel_sale(
                sale=sale,
                reason=form.cleaned_data['reason'],
                refund_payment_method=form.cleaned_data['refund_payment_method'],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            if refund_amount > 0:
                messages.success(
                    request,
                    _('Vente #%(id)s annulée. Remboursement tracé : %(amount)s FCFA.') % {
                        'id': sale.id, 'amount': f'{refund_amount:,.0f}',
                    }
                )
            else:
                messages.success(
                    request,
                    _("Vente #%(id)s annulée. Aucune sortie de trésorerie n'était nécessaire.") % {'id': sale.id}
                )
    else:
        error_text = ' '.join(
            ' '.join(errors) for errors in form.errors.values()
        )
        messages.error(request, error_text or _("Impossible d'annuler la vente."))

    return redirect(redirect_to)


@login_required
@module_required('sales')
@require_POST
def partial_return_sale(request, sale_id):
    """Retour partiel d'une vente depuis l'historique."""
    sale = get_object_or_404(
        Sale.objects.select_related('client', 'staff', 'daily', 'daily__exercise', 'credit_info'),
        id=sale_id,
    )
    form = SalePartialReturnForm(request.POST, sale=sale)
    redirect_to = _safe_next(request, 'sales_history')

    if form.is_valid():
        try:
            sale_return, refund_amount = SaleService.partial_return_sale(
                sale=sale,
                returned_items=form.cleaned_data['returned_items'],
                reason=form.cleaned_data['reason'],
                refund_payment_method=form.cleaned_data['refund_payment_method'],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            if refund_amount > 0:
                messages.success(
                    request,
                    _('Retour partiel enregistré sur la vente #%(id)s (%(total)s FCFA). Remboursement tracé : %(amount)s FCFA.') % {
                        'id': sale.id, 'total': f'{sale_return.total:,.0f}', 'amount': f'{refund_amount:,.0f}',
                    }
                )
            else:
                messages.success(
                    request,
                    _("Retour partiel enregistré sur la vente #%(id)s (%(total)s FCFA). Aucune sortie de trésorerie supplémentaire n'était nécessaire.") % {
                        'id': sale.id, 'total': f'{sale_return.total:,.0f}',
                    }
                )
    else:
        error_text = ' '.join(
            ' '.join(errors) for errors in form.errors.values()
        )
        messages.error(request, error_text or _("Impossible d'enregistrer le retour partiel."))

    return redirect(redirect_to)


@login_required
@module_required('supplies')
@require_POST
def cancel_supply(request, supply_id):
    """Annulation totale d'un approvisionnement depuis l'historique."""
    supply = get_object_or_404(
        Supply.objects.select_related('product', 'supplier', 'staff', 'daily', 'daily__exercise', 'credit_info'),
        id=supply_id,
    )
    form = SupplyCancellationForm(request.POST, supply=supply)
    redirect_to = _safe_next(request, 'supplies')

    if form.is_valid():
        try:
            refund_amount = SupplyService.cancel_supply(
                supply=supply,
                reason=form.cleaned_data['reason'],
                refund_payment_method=form.cleaned_data['refund_payment_method'],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            if refund_amount > 0:
                messages.success(
                    request,
                    _('Approvisionnement #%(id)s annulé. Remboursement fournisseur tracé : %(amount)s FCFA.') % {
                        'id': supply.id, 'amount': f'{refund_amount:,.0f}',
                    }
                )
            else:
                messages.success(
                    request,
                    _("Approvisionnement #%(id)s annulé. Aucun remboursement fournisseur supplémentaire n'était attendu.") % {'id': supply.id}
                )
    else:
        error_text = ' '.join(
            ' '.join(errors) for errors in form.errors.values()
        )
        messages.error(request, error_text or _("Impossible d'annuler l'approvisionnement."))

    return redirect(redirect_to)


@login_required
@module_required('supplies')
@require_POST
def partial_return_supply(request, supply_id):
    """Retour partiel d'un approvisionnement depuis l'historique."""
    supply = get_object_or_404(
        Supply.objects.select_related('product', 'supplier', 'staff', 'daily', 'daily__exercise', 'credit_info'),
        id=supply_id,
    )
    form = SupplyPartialReturnForm(request.POST, supply=supply)
    redirect_to = _safe_next(request, 'supplies')

    if form.is_valid():
        try:
            supply_return, refund_amount = SupplyService.partial_return_supply(
                supply=supply,
                returned_quantity=form.cleaned_data['returned_quantity'],
                reason=form.cleaned_data['reason'],
                refund_payment_method=form.cleaned_data['refund_payment_method'],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            if refund_amount > 0:
                messages.success(
                    request,
                    _("Retour partiel enregistré sur l'approvisionnement #%(id)s (%(total)s FCFA). Remboursement fournisseur tracé : %(amount)s FCFA.") % {
                        'id': supply.id, 'total': f'{supply_return.total:,.0f}', 'amount': f'{refund_amount:,.0f}',
                    }
                )
            else:
                messages.success(
                    request,
                    _("Retour partiel enregistré sur l'approvisionnement #%(id)s (%(total)s FCFA). Aucune entrée de trésorerie supplémentaire n'était attendue.") % {
                        'id': supply.id, 'total': f'{supply_return.total:,.0f}',
                    }
                )
    else:
        error_text = ' '.join(
            ' '.join(errors) for errors in form.errors.values()
        )
        messages.error(request, error_text or _("Impossible d'enregistrer le retour partiel."))

    return redirect(redirect_to)


@login_required
@module_required('products')
def products(request):
    """Vue de la page des produits avec pagination et filtres"""
    # Récupérer les paramètres de filtre
    search = request.GET.get('search', '').strip()
    category_id = _clean_int_param(request, 'category')
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
        'page_title': _('Produits'),
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


@login_required
@module_required('products')
def add_product(request):
    """Créer un produit depuis le back-office web (passe par ProductService)."""
    from core.services.product_service import ProductService

    if request.method == 'POST':
        form = ProductForm(request.POST, editing=False)
        if form.is_valid():
            validated_data = dict(form.cleaned_data)
            images = request.FILES.getlist('images')
            daily = DailyService.get_or_create_active_daily()
            try:
                product = ProductService.create_product(
                    validated_data=validated_data,
                    images=images,
                    staff=request.user,
                    daily=daily,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, _('Produit "%(name)s" créé avec succès.') % {'name': product.name})
                return redirect('product_detail', pk=product.pk)
    else:
        form = ProductForm(editing=False)

    context = {
        'page_title': _('Nouveau produit'),
        'form': form,
        'form_title': _('Nouveau produit'),
        'form_subtitle': _('Créer un nouveau produit'),
        'back_url': 'products',
    }
    return render(request, 'core/product_form.html', context)


@login_required
@module_required('products')
def edit_product(request, pk):
    """Modifier un produit existant (le stock ne se modifie pas ici)."""
    from core.services.product_service import ProductService

    product = get_object_or_404(Product, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product, editing=True)
        if form.is_valid():
            images = request.FILES.getlist('images')
            ProductService.update_product(product, dict(form.cleaned_data), images=images)
            messages.success(request, _('Produit "%(name)s" modifié avec succès.') % {'name': product.name})
            return redirect('product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product, editing=True)

    context = {
        'page_title': _('Modifier %(name)s') % {'name': product.name},
        'form': form,
        'form_title': _('Modifier le produit'),
        'form_subtitle': _('Modifier les informations de %(name)s') % {'name': product.name},
        'back_url': 'product_detail',
        'back_pk': product.pk,
        'product_images': product.images.filter(delete_at__isnull=True).order_by('-is_primary', 'id'),
    }
    return render(request, 'core/product_form.html', context)


@login_required
@module_required('products')
@require_http_methods(['POST'])
def delete_product(request, pk):
    """Désactive (soft-delete) un produit ; l'historique de ventes/appro est conservé."""
    product = get_object_or_404(Product, pk=pk, delete_at__isnull=True)
    product.delete_at = timezone.now()
    product.save(update_fields=['delete_at'])
    messages.success(request, _('Produit "%(name)s" désactivé.') % {'name': product.name})
    return redirect('products')


PRODUCT_IMPORT_MAX_BYTES = 1 * 1024 * 1024   # 1 Mo
PRODUCT_IMPORT_MAX_ROWS = 5000


@login_required
@module_required('products')
def export_products_csv(request):
    """Export du catalogue produit en CSV, support d'une mise à jour de prix en masse."""
    import csv

    products = Product.objects.filter(delete_at__isnull=True).select_related(
        'category', 'gamme', 'rayon', 'grammage_type',
    ).order_by('name')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response.write('﻿')  # BOM UTF-8 pour Excel
    response['Content-Disposition'] = 'attachment; filename="catalogue_produits.csv"'
    writer = _SafeCsvWriter(csv.writer(response, delimiter=';'))
    writer.writerow([
        _('Code'), _('Nom'), _('Catégorie'), _('Gamme'), _('Rayon'), _('Type de grammage'),
        _('Stock (lecture seule)'), _('Seuil de stock'), _('Prix actuel'), _('Prix maximum'),
        _("Prix d'achat"), _('TVA applicable'), _('Prix réductible'),
    ])
    for product in products:
        writer.writerow([
            product.code,
            product.name,
            product.category.name if product.category else '',
            product.gamme.name if product.gamme else '',
            product.rayon.name if product.rayon else '',
            product.grammage_type.name if product.grammage_type else '',
            product.stock,
            product.stock_limit if product.stock_limit is not None else '',
            product.actual_price if product.actual_price is not None else '',
            product.max_salable_price if product.max_salable_price is not None else '',
            product.last_purchase_price if product.last_purchase_price is not None else '',
            'Oui' if product.has_vat else 'Non',
            'Oui' if product.is_price_reducible else 'Non',
        ])
    return response


@login_required
@module_required('products')
@require_http_methods(['POST'])
def import_products_csv(request):
    """
    Mise à jour en masse des prix/seuils du catalogue depuis un CSV exporté
    par ``export_products_csv``.

    Ne crée jamais de produit et ne touche jamais au stock : comme partout
    ailleurs (``ProductService.update_product``, API mobile), le stock ne
    change que par approvisionnement ou inventaire, jamais par une édition
    directe du produit.
    """
    import csv
    import io
    from decimal import Decimal, InvalidOperation

    file = request.FILES.get('file')
    if not file:
        messages.error(request, _("Aucun fichier sélectionné."))
        return redirect('products')
    if not file.name.lower().endswith('.csv'):
        messages.error(request, _("Le fichier doit être au format CSV."))
        return redirect('products')
    if file.size > PRODUCT_IMPORT_MAX_BYTES:
        messages.error(request, _("Fichier trop volumineux (1 Mo maximum)."))
        return redirect('products')

    try:
        decoded = file.read(PRODUCT_IMPORT_MAX_BYTES + 1).decode('utf-8-sig')
    except UnicodeDecodeError:
        messages.error(request, _("Le fichier doit être encodé en UTF-8."))
        return redirect('products')

    reader = csv.reader(io.StringIO(decoded), delimiter=';')
    next(reader, None)  # en-tête

    def parse_decimal(value):
        value = (value or '').strip().replace(',', '.')
        if not value:
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    def parse_int(value):
        value = (value or '').strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    updated = 0
    errors = []

    try:
        with transaction.atomic():
            for row_num, row in enumerate(reader, start=2):
                if row_num - 1 > PRODUCT_IMPORT_MAX_ROWS:
                    raise ValueError(_("Trop de lignes (maximum %(max)s).") % {'max': PRODUCT_IMPORT_MAX_ROWS})
                if not row or not row[0].strip():
                    continue

                code = row[0].strip()
                product = Product.objects.filter(
                    code=code, delete_at__isnull=True,
                ).select_for_update().first()
                if product is None:
                    errors.append(
                        _("Ligne %(row)s: produit « %(code)s » introuvable (import ignoré, aucune création).") % {
                            'row': row_num, 'code': code,
                        }
                    )
                    continue

                has_vat_raw = row[11].strip() if len(row) > 11 else ''
                reducible_raw = row[12].strip() if len(row) > 12 else ''

                product.stock_limit = parse_int(row[7]) if len(row) > 7 else None
                product.actual_price = parse_decimal(row[8]) if len(row) > 8 else None
                product.max_salable_price = parse_decimal(row[9]) if len(row) > 9 else None
                product.last_purchase_price = parse_decimal(row[10]) if len(row) > 10 else None
                if has_vat_raw:
                    product.has_vat = has_vat_raw.lower() != 'non'
                if reducible_raw:
                    product.is_price_reducible = reducible_raw.lower() != 'non'

                product.save(update_fields=[
                    'stock_limit', 'actual_price', 'max_salable_price',
                    'last_purchase_price', 'has_vat', 'is_price_reducible',
                ])
                updated += 1
    except ValueError as exc:
        messages.error(request, _("Import annulé : %(error)s") % {'error': exc})
        return redirect('products')
    except Exception:
        logger.exception("Erreur lors de l'import du catalogue produit")
        messages.error(request, _("Import annulé : erreur interne. Aucune modification n'a été enregistrée."))
        return redirect('products')

    if updated:
        messages.success(request, _("%(count)s produit(s) mis à jour.") % {'count': updated})
    if errors:
        for error in errors[:10]:
            messages.warning(request, error)
        if len(errors) > 10:
            messages.warning(request, _("... et %(count)s erreur(s) supplémentaire(s).") % {'count': len(errors) - 10})
    if not updated and not errors:
        messages.warning(request, _("Aucune ligne exploitable dans le fichier."))

    return redirect('products')


# ── Données de référence produit (catégories, gammes, rayons, grammages) ──

REFERENCE_MODELS = {
    'categories': Category,
    'gammes': Gamme,
    'rayons': Rayon,
    'grammage-types': GrammageType,
}


def _reference_labels():
    """Construit les libellés à l'appel pour que gettext utilise la langue active."""
    return {
        'categories': (_('Catégories'), _('Catégorie')),
        'gammes': (_('Gammes'), _('Gamme')),
        'rayons': (_('Rayons'), _('Rayon')),
        'grammage-types': (_('Types de grammage'), _('Type de grammage')),
    }


@login_required
@module_required('products')
def product_references(request):
    """Gestion des catégories / gammes / rayons / types de grammage."""
    labels = _reference_labels()
    kind = request.GET.get('tab', 'categories')
    model = REFERENCE_MODELS.get(kind)
    if model is None:
        kind = 'categories'
        model = Category

    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    queryset = model.objects.filter(delete_at__isnull=True)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))

    paginator = Paginator(queryset.order_by('name'), 20)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': _('Catégories, gammes, rayons et grammages'),
        'current_tab': kind,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
        'reference_tabs': [(key, plural) for key, (plural, singular) in labels.items()],
        'current_label_plural': labels[kind][0],
        'current_label_singular': labels[kind][1],
    }
    return render(request, 'core/product_references.html', context)


@login_required
@module_required('products')
def add_reference(request, kind):
    """Créer une catégorie/gamme/rayon/type de grammage."""
    model = REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    labels = _reference_labels()
    plural, singular = labels[kind]

    if request.method == 'POST':
        form = ReferenceDataForm(request.POST)
        if form.is_valid():
            model.objects.create(
                name=form.cleaned_data['name'],
                description=form.cleaned_data['description'],
            )
            messages.success(request, _('"%(name)s" créé avec succès.') % {'name': form.cleaned_data['name']})
            return redirect(f"{reverse('product_references')}?tab={kind}")
    else:
        form = ReferenceDataForm()

    context = {
        'page_title': _('Nouveau : %(label)s') % {'label': singular},
        'form': form,
        'form_title': _('Nouveau : %(label)s') % {'label': singular},
        'form_subtitle': _('Créer un nouvel élément dans « %(label)s »') % {'label': plural},
        'back_url': 'product_references',
        'back_tab': kind,
    }
    return render(request, 'core/reference_form.html', context)


@login_required
@module_required('products')
def edit_reference(request, kind, pk):
    """Modifier une catégorie/gamme/rayon/type de grammage."""
    model = REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    labels = _reference_labels()
    plural, singular = labels[kind]
    instance = get_object_or_404(model, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = ReferenceDataForm(request.POST)
        if form.is_valid():
            instance.name = form.cleaned_data['name']
            instance.description = form.cleaned_data['description']
            instance.save(update_fields=['name', 'description'])
            messages.success(request, _('"%(name)s" modifié avec succès.') % {'name': instance.name})
            return redirect(f"{reverse('product_references')}?tab={kind}")
    else:
        form = ReferenceDataForm(initial={'name': instance.name, 'description': instance.description})

    context = {
        'page_title': _('Modifier : %(name)s') % {'name': instance.name},
        'form': form,
        'form_title': _('Modifier : %(label)s') % {'label': singular},
        'form_subtitle': _('Modifier les informations de %(name)s') % {'name': instance.name},
        'back_url': 'product_references',
        'back_tab': kind,
    }
    return render(request, 'core/reference_form.html', context)


@login_required
@module_required('products')
@require_http_methods(['POST'])
def delete_reference(request, kind, pk):
    """Désactive (soft-delete) une catégorie/gamme/rayon/type de grammage."""
    model = REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    instance = get_object_or_404(model, pk=pk, delete_at__isnull=True)
    if instance.products.filter(delete_at__isnull=True).exists():
        messages.error(
            request,
            _("Impossible de désactiver « %(name)s » : des produits actifs y sont encore rattachés.") % {'name': instance.name},
        )
    else:
        instance.delete_at = timezone.now()
        instance.save(update_fields=['delete_at'])
        messages.success(request, _('"%(name)s" désactivé.') % {'name': instance.name})
    return redirect(f"{reverse('product_references')}?tab={kind}")


# ── Données de référence comptables (taux de TVA, types de recette/dépense) ──

ACCOUNTING_REFERENCE_MODELS = {
    'taux-tva': TaxRate,
    'types-recette': RecipeType,
    'types-depense': ExpenseType,
}


def _accounting_reference_labels():
    """Construit les libellés à l'appel pour que gettext utilise la langue active."""
    return {
        'taux-tva': (_('Taux de TVA'), _('Taux de TVA')),
        'types-recette': (_('Types de recette'), _('Type de recette')),
        'types-depense': (_('Types de dépense'), _('Type de dépense')),
    }


def _accounting_reference_form_class(kind):
    return TaxRateForm if kind == 'taux-tva' else ReferenceDataForm


def _accounting_reference_in_use(instance, kind):
    """Un taux/type encore rattaché à des enregistrements actifs ne peut pas être désactivé."""
    if kind == 'taux-tva':
        return instance.supplies.filter(delete_at__isnull=True).exists()
    if kind == 'types-recette':
        return instance.daily_recipes.filter(delete_at__isnull=True).exists()
    if kind == 'types-depense':
        return (
            instance.daily_expenses.filter(delete_at__isnull=True).exists()
            or instance.supplies.filter(delete_at__isnull=True).exists()
        )
    return False


@login_required
@module_required('accounting')
def accounting_references(request):
    """Gestion des taux de TVA, types de recette et types de dépense."""
    labels = _accounting_reference_labels()
    kind = request.GET.get('tab', 'taux-tva')
    model = ACCOUNTING_REFERENCE_MODELS.get(kind)
    if model is None:
        kind = 'taux-tva'
        model = TaxRate

    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    queryset = model.objects.filter(delete_at__isnull=True)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))

    order_by = 'rate' if kind == 'taux-tva' else 'name'
    paginator = Paginator(queryset.order_by(order_by), 20)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': _('Taux de TVA, types de recette et de dépense'),
        'current_tab': kind,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
        'reference_tabs': [(key, plural) for key, (plural, singular) in labels.items()],
        'current_label_plural': labels[kind][0],
        'current_label_singular': labels[kind][1],
    }
    return render(request, 'core/accounting_references.html', context)


@login_required
@module_required('accounting')
def add_accounting_reference(request, kind):
    """Créer un taux de TVA / type de recette / type de dépense."""
    model = ACCOUNTING_REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    labels = _accounting_reference_labels()
    plural, singular = labels[kind]
    form_class = _accounting_reference_form_class(kind)

    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            with transaction.atomic():
                if kind == 'taux-tva':
                    instance = form.save(commit=False)
                    if instance.is_default:
                        TaxRate.objects.filter(is_default=True).update(is_default=False)
                    instance.save()
                else:
                    instance = model.objects.create(
                        name=form.cleaned_data['name'],
                        description=form.cleaned_data['description'],
                    )
            messages.success(request, _('"%(name)s" créé avec succès.') % {'name': instance.name})
            return redirect(f"{reverse('accounting_references')}?tab={kind}")
    else:
        form = form_class()

    context = {
        'page_title': _('Nouveau : %(label)s') % {'label': singular},
        'form': form,
        'form_title': _('Nouveau : %(label)s') % {'label': singular},
        'form_subtitle': _('Créer un nouvel élément dans « %(label)s »') % {'label': plural},
        'back_url': 'accounting_references',
        'back_tab': kind,
    }
    return render(request, 'core/reference_form.html', context)


@login_required
@module_required('accounting')
def edit_accounting_reference(request, kind, pk):
    """Modifier un taux de TVA / type de recette / type de dépense."""
    model = ACCOUNTING_REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    labels = _accounting_reference_labels()
    plural, singular = labels[kind]
    instance = get_object_or_404(model, pk=pk, delete_at__isnull=True)
    form_class = _accounting_reference_form_class(kind)

    if request.method == 'POST':
        form = form_class(request.POST, instance=instance) if kind == 'taux-tva' else form_class(request.POST)
        if form.is_valid():
            with transaction.atomic():
                if kind == 'taux-tva':
                    instance = form.save(commit=False)
                    if instance.is_default:
                        TaxRate.objects.filter(is_default=True).exclude(pk=instance.pk).update(is_default=False)
                    instance.save()
                else:
                    instance.name = form.cleaned_data['name']
                    instance.description = form.cleaned_data['description']
                    instance.save(update_fields=['name', 'description'])
            messages.success(request, _('"%(name)s" modifié avec succès.') % {'name': instance.name})
            return redirect(f"{reverse('accounting_references')}?tab={kind}")
    else:
        if kind == 'taux-tva':
            form = form_class(instance=instance)
        else:
            form = form_class(initial={'name': instance.name, 'description': instance.description})

    context = {
        'page_title': _('Modifier : %(name)s') % {'name': instance.name},
        'form': form,
        'form_title': _('Modifier : %(label)s') % {'label': singular},
        'form_subtitle': _('Modifier les informations de %(name)s') % {'name': instance.name},
        'back_url': 'accounting_references',
        'back_tab': kind,
    }
    return render(request, 'core/reference_form.html', context)


@login_required
@module_required('accounting')
@require_http_methods(['POST'])
def delete_accounting_reference(request, kind, pk):
    """Désactive (soft-delete) un taux de TVA / type de recette / type de dépense."""
    model = ACCOUNTING_REFERENCE_MODELS.get(kind)
    if model is None:
        raise Http404
    instance = get_object_or_404(model, pk=pk, delete_at__isnull=True)
    if _accounting_reference_in_use(instance, kind):
        messages.error(
            request,
            _("Impossible de désactiver « %(name)s » : des enregistrements actifs y sont encore rattachés.") % {'name': instance.name},
        )
    else:
        instance.delete_at = timezone.now()
        instance.save(update_fields=['delete_at'])
        messages.success(request, _('"%(name)s" désactivé.') % {'name': instance.name})
    return redirect(f"{reverse('accounting_references')}?tab={kind}")


INVENTORY_PER_PAGE_CHOICES = [10, 25, 50, 100]


@login_required
@module_required('inventory')
def inventory(request):
    """Vue de la page de l'inventaire avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    staff_id = _clean_int_param(request, 'staff')
    exercise_id = _clean_int_param(request, 'exercise')
    if not exercise_id and 'exercise' not in request.GET:
        # Par défaut, sélectionner l'exercice en cours
        current_ex = ExerciseService.get_or_create_current_exercise()
        exercise_id = str(current_ex.id)
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')
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
        'page_title': _('Inventaire'),
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
                _('Inventaire pour "%(product)s" enregistré avec succès (%(valid)s valides, %(invalid)s invalides).') % {
                    'product': inventory_record.product.name,
                    'valid': inventory_record.valid_product_count,
                    'invalid': inventory_record.invalid_product_count,
                }
            )
            return redirect('inventory')
    else:
        form = InventoryForm()

    context = {
        'page_title': _('Nouvel enregistrement d\'inventaire'),
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
        'page_title': _('Clôturer l\'inventaire'),
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
        messages.error(request, _('Aucun inventaire à clôturer pour l\'exercice courant.'))
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

        # NB : la clôture d'inventaire ne ferme PAS l'exercice comptable.
        # La clôture d'exercice (résultat, à-nouveaux) se fait depuis
        # Comptabilité > Clôture d'exercice.

    messages.success(
        request,
        _('Inventaire clôturé avec succès. Stock mis à jour pour %(count)s produit(s).') % {'count': updated_count}
    )
    return redirect('inventory')


SNAPSHOT_PER_PAGE_CHOICES = [10, 25, 50, 100]


@login_required
@module_required('inventory')
def inventory_history(request):
    """Vue de l'historique des inventaires clôturés (InventorySnapshot)"""
    search = request.GET.get('search', '').strip()
    exercise_id = _clean_int_param(request, 'exercise')
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
        'page_title': _('Historique des inventaires'),
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
        queryset = CustomUser.objects.filter(delete_at__isnull=True)
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
        'page_title': _('Utilisateurs'),
        'current_tab': tab,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/contacts.html', context)


@login_required
@superuser_required
def add_staff(request):
    """Créer un membre du personnel (réservé aux administrateurs)."""
    if request.method == 'POST':
        form = StaffForm(request.POST, editing=False)
        if form.is_valid():
            user = form.save()
            messages.success(request, _('Compte "%(name)s" créé avec succès.') % {'name': user.username})
            return redirect(f"{reverse('contacts')}?tab=staff")
    else:
        form = StaffForm(editing=False)

    context = {
        'page_title': _('Nouveau membre du personnel'),
        'form': form,
        'form_title': _('Nouveau membre du personnel'),
        'form_subtitle': _('Créer un compte et lui attribuer des modules'),
        'back_url': 'contacts',
        'back_tab': 'staff',
    }
    return render(request, 'core/staff_form.html', context)


@login_required
@superuser_required
def edit_staff(request, pk):
    """Modifier un membre du personnel (rôle, modules, statut)."""
    from core.services.staff_service import StaffService

    staff_member = get_object_or_404(CustomUser, pk=pk, delete_at__isnull=True)
    previous_state = CustomUser.objects.get(pk=staff_member.pk)

    if request.method == 'POST':
        form = StaffForm(request.POST, instance=staff_member, editing=True)
        if form.is_valid():
            loses_admin_rights = previous_state.is_superuser and (
                not form.instance.is_superuser or not form.instance.is_active
            )
            try:
                if loses_admin_rights:
                    StaffService.ensure_not_last_superuser(previous_state)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                form.save()
                messages.success(request, _('Compte "%(name)s" modifié avec succès.') % {'name': staff_member.username})
                return redirect(f"{reverse('contacts')}?tab=staff")
    else:
        form = StaffForm(instance=staff_member, editing=True)

    context = {
        'page_title': _('Modifier %(name)s') % {'name': staff_member.get_full_name()},
        'form': form,
        'form_title': _('Modifier le membre du personnel'),
        'form_subtitle': _('Modifier le compte de %(name)s') % {'name': staff_member.get_full_name()},
        'back_url': 'contacts',
        'back_tab': 'staff',
        'staff_member': staff_member,
    }
    return render(request, 'core/staff_form.html', context)


@login_required
@superuser_required
@require_http_methods(['POST'])
def toggle_staff_active(request, pk):
    """Active/désactive un compte du personnel en un clic."""
    from core.services.staff_service import StaffService

    staff_member = get_object_or_404(CustomUser, pk=pk, delete_at__isnull=True)
    try:
        if staff_member.is_active:
            StaffService.ensure_not_last_superuser(staff_member)
            staff_member.is_active = False
            message = _('Compte "%(name)s" désactivé.') % {'name': staff_member.username}
        else:
            staff_member.is_active = True
            message = _('Compte "%(name)s" réactivé.') % {'name': staff_member.username}
        staff_member.save(update_fields=['is_active'])
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, message)
    return redirect(f"{reverse('contacts')}?tab=staff")


@login_required
@superuser_required
def reset_staff_password(request, pk):
    """Réinitialise le mot de passe d'un membre du personnel."""
    staff_member = get_object_or_404(CustomUser, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = StaffPasswordResetForm(request.POST)
        if form.is_valid():
            staff_member.set_password(form.cleaned_data['new_password1'])
            staff_member.save(update_fields=['password'])
            staff_member.revoke_api_tokens()
            messages.success(request, _('Mot de passe de "%(name)s" réinitialisé.') % {'name': staff_member.username})
            return redirect(f"{reverse('contacts')}?tab=staff")
    else:
        form = StaffPasswordResetForm()

    context = {
        'page_title': _('Réinitialiser le mot de passe'),
        'form': form,
        'form_title': _('Réinitialiser le mot de passe'),
        'form_subtitle': _('Nouveau mot de passe pour %(name)s') % {'name': staff_member.get_full_name()},
        'back_url': 'contacts',
        'back_tab': 'staff',
    }
    return render(request, 'core/staff_password_form.html', context)


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
        'page_title': _('Fournisseurs'),
        'current_search': search,
        'page_obj': page_obj,
        'suppliers': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/suppliers.html', context)


@login_required
@module_required('contacts')
def add_client(request):
    """Vue pour ajouter un nouveau client.

    Aussi utilisée en AJAX par le raccourci « + » de la page Ventes (choix
    d'un client pour une vente à crédit), à la manière d'un popup Django
    admin : la même vue répond en JSON quand elle reçoit l'en-tête
    ``X-Requested-With``, sans dupliquer la logique de création.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'id': client.id,
                    'name': str(client),
                })
            messages.success(request, _('Client "%(name)s" créé avec succès.') % {'name': form.cleaned_data['firstname']})
            return redirect('contacts')
        elif is_ajax:
            form_errors = form.errors.get_json_data()
            return JsonResponse({
                'success': False,
                'errors': {
                    field: [error['message'] for error in errors]
                    for field, errors in form_errors.items()
                    if field != '__all__'
                },
                'non_field_errors': [
                    error['message'] for error in form_errors.get('__all__', [])
                ],
            }, status=400)
    else:
        form = ClientForm()

    context = {
        'page_title': _('Nouveau client'),
        'form': form,
        'form_title': _('Nouveau client'),
        'form_subtitle': _('Créer un nouveau client'),
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
            messages.success(request, _('Client "%(name)s" modifié avec succès.') % {'name': client.get_full_name()})
            return redirect('contacts')
    else:
        form = ClientForm(instance=client)

    context = {
        'page_title': _('Modifier %(name)s') % {'name': client.get_full_name()},
        'form': form,
        'form_title': _('Modifier le client'),
        'form_subtitle': _('Modifier les informations de %(name)s') % {'name': client.get_full_name()},
        'back_url': 'contacts',
        'back_tab': 'clients',
    }
    return render(request, 'core/contacts_form.html', context)


@login_required
@module_required('contacts')
@require_http_methods(['POST'])
def delete_client(request, pk):
    """Désactive (soft-delete) un client, sauf s'il a une créance en cours."""
    client = get_object_or_404(Client, pk=pk, delete_at__isnull=True)
    has_outstanding_credit = CreditSale.objects.filter(
        sale__client=client, is_fully_paid=False, delete_at__isnull=True,
    ).exists()
    if has_outstanding_credit:
        messages.error(
            request,
            _("Impossible de désactiver « %(name)s » : une créance est encore en cours.") % {'name': client.get_full_name()},
        )
    else:
        client.delete_at = timezone.now()
        client.save(update_fields=['delete_at'])
        messages.success(request, _('Client "%(name)s" désactivé.') % {'name': client.get_full_name()})
    return redirect(f"{reverse('contacts')}?tab=clients")


@login_required
@module_required('suppliers')
def add_supplier(request):
    """Vue pour ajouter un nouveau fournisseur"""
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Fournisseur "%(name)s" créé avec succès.') % {'name': form.cleaned_data['name']})
            return redirect('suppliers')
    else:
        form = SupplierForm()

    context = {
        'page_title': _('Nouveau fournisseur'),
        'form': form,
        'form_title': _('Nouveau fournisseur'),
        'form_subtitle': _('Créer un nouveau fournisseur'),
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
            messages.success(request, _('Fournisseur "%(name)s" modifié avec succès.') % {'name': supplier.name})
            return redirect('suppliers')
    else:
        form = SupplierForm(instance=supplier)

    context = {
        'page_title': _('Modifier %(name)s') % {'name': supplier.name},
        'form': form,
        'form_title': _('Modifier le fournisseur'),
        'form_subtitle': _('Modifier les informations de %(name)s') % {'name': supplier.name},
        'back_url': 'suppliers',
    }
    return render(request, 'core/supplier_form.html', context)


@login_required
@module_required('suppliers')
@require_http_methods(['POST'])
def delete_supplier(request, pk):
    """Désactive (soft-delete) un fournisseur, sauf s'il a une dette en cours."""
    supplier = get_object_or_404(Supplier, pk=pk, delete_at__isnull=True)
    has_outstanding_credit = CreditSupply.objects.filter(
        supply__supplier=supplier, is_fully_paid=False, delete_at__isnull=True,
    ).exists()
    if has_outstanding_credit:
        messages.error(
            request,
            _("Impossible de désactiver « %(name)s » : une dette fournisseur est encore en cours.") % {'name': supplier.name},
        )
    else:
        supplier.delete_at = timezone.now()
        supplier.save(update_fields=['delete_at'])
        messages.success(request, _('Fournisseur "%(name)s" désactivé.') % {'name': supplier.name})
    return redirect('suppliers')


@login_required
@module_required('supplies')
def supplies(request):
    """Vue de la page des approvisionnements avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    supplier_id = _clean_int_param(request, 'supplier')
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')
    page_number = request.GET.get('page', 1)

    queryset = Supply.objects.filter(
        delete_at__isnull=True,
    ).select_related('product', 'supplier', 'staff', 'daily', 'credit_info').prefetch_related('supply_returns')

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
        'page_title': _('Approvisionnement'),
        'page_obj': page_obj,
        'supplies': page_obj.object_list,
        'suppliers': suppliers_for_filter,
        'current_search': search,
        'current_supplier': supplier_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'current_full_path': request.get_full_path(),
        'payment_method_choices': PAYMENT_METHOD_CHOICES,
        'total_count': paginator.count,
    }
    return render(request, 'core/supplies.html', context)


@login_required
@module_required('supplies')
@transaction.atomic
def add_supply(request):
    """Vue pour ajouter un nouvel approvisionnement"""
    if request.method == 'POST':
        form = SupplyForm(request.POST)
        if form.is_valid():
            supply = form.save(commit=False)
            supply.staff = request.user
            supply.daily = DailyService.get_or_create_active_daily()
            supply.total_price = supply.quantity * supply.purchase_cost
            is_credit_purchase = form.cleaned_data.get('is_credit', False)
            supply.is_credit = is_credit_purchase
            supply.selling_price = form.cleaned_data.get('selling_price') or supply.product.actual_price or 0
            supply.is_paid = not is_credit_purchase
            supply.payment_method = form.cleaned_data.get('payment_method', 'CASH')

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
                if settings.default_supply_expense_type_id != selected_expense_type.pk:
                    settings.default_supply_expense_type = selected_expense_type
                    settings.save(update_fields=['default_supply_expense_type'])
            
            supply.save()

            # Enregistrer l'écriture comptable
            try:
                AccountingService.record_supply(
                    supply=supply,
                    daily=supply.daily,
                    exercise=supply.daily.exercise,
                    payment_method=supply.payment_method,
                    is_credit=is_credit_purchase,
                    tax_rate=supply.tax_rate,  # Passer le taux de TVA depuis l'approvisionnement
                )
            except Exception:
                logger.exception("Écriture comptable impossible pour l'approvisionnement #%s", supply.pk)

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

            # Mettre à jour le stock du produit (sous verrou : une vente
            # concurrente ne doit pas écraser la mise à jour)
            product = Product.objects.select_for_update().get(pk=supply.product_id)
            product.stock = (product.stock or 0) + supply.quantity
            # Mettre à jour le dernier prix d'achat
            product.last_purchase_price = supply.purchase_cost
            update_fields = ['stock', 'last_purchase_price']
            # Le prix de vente public n'est modifiable que par un utilisateur
            # ayant le module « produits »
            selling_price = form.cleaned_data.get('selling_price')
            if selling_price and request.user.has_module_access('products'):
                product.actual_price = selling_price
                update_fields.append('actual_price')
            product.save(update_fields=update_fields)

            # Retourner JSON si c'est une requête AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': _('Approvisionnement de %(quantity)s x "%(product)s" enregistré avec succès.') % {
                        'quantity': supply.quantity, 'product': product.name,
                    },
                    'product_name': product.name,
                    'quantity': supply.quantity,
                    'unit_price': float(supply.purchase_cost),
                    'purchase_cost': float(supply.purchase_cost),
                    'total_price': float(supply.total_price),
                    'vat_amount': float(supply.vat_amount) if supply.vat_amount else 0,
                    'expense_type_id': supply.expense_type_id if supply.expense_type else None,
                    'payment_method': supply.payment_method,
                })

            messages.success(request, _('Approvisionnement de %(quantity)s x "%(product)s" enregistré avec succès.') % {
                'quantity': supply.quantity, 'product': product.name,
            })
            return redirect('supplies')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                form_errors = form.errors.get_json_data()
                return JsonResponse({
                    'success': False,
                    'errors': {
                        field: [error['message'] for error in errors]
                        for field, errors in form_errors.items()
                        if field != '__all__'
                    },
                    'non_field_errors': [
                        error['message'] for error in form_errors.get('__all__', [])
                    ],
                }, status=400)

            form = SupplyForm(request.POST)  # Re-render form with errors
            return render(request, 'core/supplies_add.html', {
                'page_title': _('Nouvel approvisionnement'),
                'form': form,
            })
    else:
        form = SupplyForm()

    context = {
        'page_title': _('Nouvel approvisionnement'),
        'form': form,
    }
    return render(request, 'core/supplies_add.html', context)


# ── Commandes fournisseurs (statut ORDERED, distinct de la réception) ──

@login_required
@module_required('supplies')
def purchase_orders(request):
    """Liste des commandes fournisseurs en attente de réception."""
    from core.models.inventory_models import PurchaseOrder

    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)

    queryset = PurchaseOrder.objects.filter(
        status='ORDERED', delete_at__isnull=True,
    ).select_related('product', 'supplier', 'staff')

    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search) | Q(product__code__icontains=search) | Q(supplier__name__icontains=search)
        )
    queryset = queryset.order_by('-create_at')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': _('Commandes fournisseurs'),
        'page_obj': page_obj,
        'orders': page_obj.object_list,
        'current_search': search,
        'total_count': paginator.count,
    }
    return render(request, 'core/purchase_orders.html', context)


@login_required
@module_required('supplies')
def add_purchase_order(request):
    """Passe une commande fournisseur : aucun effet sur le stock ni la comptabilité."""
    from core.forms import PurchaseOrderForm
    from core.services.supply_service import SupplyService

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            order = SupplyService.create_purchase_order(
                product=form.cleaned_data['product'],
                supplier=form.cleaned_data.get('supplier'),
                quantity=form.cleaned_data['quantity'],
                purchase_cost=form.cleaned_data['purchase_cost'],
                staff=request.user,
                daily=DailyService.get_or_create_active_daily(),
            )
            messages.success(request, _('Commande de %(quantity)s x "%(product)s" enregistrée.') % {
                'quantity': order.quantity, 'product': order.product.name,
            })
            return redirect('purchase_orders')
    else:
        form = PurchaseOrderForm()

    context = {
        'page_title': _('Nouvelle commande fournisseur'),
        'form': form,
    }
    return render(request, 'core/purchase_order_form.html', context)


@login_required
@module_required('supplies')
def receive_purchase_order(request, pk):
    """Réceptionne une commande fournisseur : applique le stock et l'écriture comptable."""
    from core.forms import ReceiveSupplyForm
    from core.models.inventory_models import PurchaseOrder
    from core.services.supply_service import SupplyService

    order = get_object_or_404(PurchaseOrder, pk=pk, status='ORDERED', delete_at__isnull=True)

    if request.method == 'POST':
        form = ReceiveSupplyForm(request.POST, product=order.product)
        if form.is_valid():
            try:
                SupplyService.receive_purchase_order(
                    order,
                    purchase_cost=form.cleaned_data['purchase_cost'],
                    selling_price=form.cleaned_data.get('selling_price'),
                    payment_method=form.cleaned_data.get('payment_method', 'CASH'),
                    is_credit=form.cleaned_data.get('is_credit', False),
                    due_date=form.cleaned_data.get('due_date'),
                    tax_rate=form.cleaned_data.get('tax_rate'),
                    expense_type=form.cleaned_data.get('expense_type'),
                    can_update_selling_price=request.user.has_module_access('products'),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, _('Commande de "%(product)s" réceptionnée : stock mis à jour.') % {
                    'product': order.product.name,
                })
                return redirect('supplies')
    else:
        form = ReceiveSupplyForm(product=order.product, initial={
            'purchase_cost': order.estimated_purchase_cost,
            'selling_price': order.product.actual_price,
        })

    context = {
        'page_title': _('Réceptionner la commande – %(product)s') % {'product': order.product.name},
        'form': form,
        'order': order,
    }
    return render(request, 'core/receive_purchase_order.html', context)


@login_required
@module_required('supplies')
@require_http_methods(['POST'])
def cancel_purchase_order(request, pk):
    """Annule une commande fournisseur non encore réceptionnée."""
    from core.models.inventory_models import PurchaseOrder
    from core.services.supply_service import SupplyService

    order = get_object_or_404(PurchaseOrder, pk=pk, delete_at__isnull=True)
    try:
        SupplyService.cancel_purchase_order(order)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _('Commande de "%(product)s" annulée.') % {'product': order.product.name})
    return redirect('purchase_orders')


@login_required
@module_required('expenses')
def expenses(request):
    """Vue de la page des dépenses et recettes quotidiennes avec pagination et filtres"""
    # Paramètres communs
    search = request.GET.get('search', '').strip()
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')
    page_number = request.GET.get('page', 1)
    active_tab = request.GET.get('tab', 'expenses')
    
    # === DéPENSES ===
    expense_type_id = _clean_int_param(request, 'expense_type')
    
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
        'page_title': _('Dépenses/Recettes'),
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

            # Enregistrer l'écriture comptable. Une erreur ne bloque pas la
            # dépense (continuité de service en caisse) mais n'est plus
            # silencieuse : elle est journalisée et la dépense est marquée
            # « à rejouer » (``manage.py replay_accounting``).
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            AccountingService.safe_record_expense(
                expense=expense,
                daily=daily,
                exercise=daily.exercise,
                payment_method=payment_method,
            )

            messages.success(request, _('Dépense de %(amount)s FCFA enregistrée avec succès.') % {'amount': f'{expense.amount:,.0f}'})
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
        'page_title': _('Nouvelle dépense'),
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

            # Enregistrer l'écriture comptable (voir add_expense : plus de
            # perte silencieuse, marquage accounting_pending sur échec).
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            AccountingService.safe_record_expense(
                expense=expense,
                daily=daily,
                exercise=daily.exercise,
                payment_method=payment_method,
            )

            return JsonResponse({
                'success': True,
                'message': _('Dépense de %(amount)sFCFA enregistrée avec succès.') % {'amount': f'{expense.amount:,.0f}'},
                'expense_id': expense.id,
            })
        else:
            return JsonResponse({
                'success': False,
                'error': _('Formulaire invalide'),
                'errors': form.errors,
            }, status=400)
    except Exception:
        logger.exception("Erreur lors de l'ajout d'une dépense (AJAX)")
        return JsonResponse({
            'success': False,
            'error': _("Une erreur interne est survenue. Réessayez ou contactez l'administrateur."),
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

            # Enregistrer l'écriture comptable. Une erreur ne bloque pas la
            # recette (continuité de service en caisse) mais n'est plus
            # silencieuse : elle est journalisée et la recette est marquée
            # « à rejouer » (``manage.py replay_accounting``).
            payment_method = form.cleaned_data.get('payment_method', 'CASH')
            AccountingService.safe_record_recipe(
                recipe=recipe,
                daily=daily,
                exercise=daily.exercise,
                payment_method=payment_method,
            )

            messages.success(request, _('Recette de %(amount)s FCFA enregistrée avec succès.') % {'amount': f'{recipe.amount:,.0f}'})
            return redirect('expenses')
    else:
        form = RecipeForm()

    context = {
        'page_title': _('Nouvelle recette'),
        'form': form,
    }
    return render(request, 'core/recipes_add.html', context)


@login_required
@module_required('reports')
def reports(request):
    """Vue de la page des rapports"""
    context = {
        'page_title': _('Rapports')
    }
    return render(request, 'core/reports.html', context)


@login_required
@module_required('dashboard')
def get_daily_summary(request):
    """API pour récupérer le résumé de la journée en cours"""
    from core.models.inventory_models import DailyInventory

    current_daily = DailyService.get_or_create_active_daily()

    if not current_daily:
        return JsonResponse({'success': False, 'message': _('Aucune journée active trouvée.')}, status=404)

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


def _parse_money(value, field_label):
    """Convertit une valeur JSON en Decimal >= 0 (max 10 chiffres), ou lève ValueError."""
    from decimal import Decimal, InvalidOperation
    if value is None or value == '':
        return Decimal('0')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(_("%(field)s : montant invalide.") % {'field': field_label})
    if not amount.is_finite():
        raise ValueError(_("%(field)s : montant invalide.") % {'field': field_label})
    if amount < 0:
        raise ValueError(_("%(field)s : le montant ne peut pas être négatif.") % {'field': field_label})
    if amount >= Decimal('100000000'):
        raise ValueError(_("%(field)s : montant trop élevé.") % {'field': field_label})
    return amount.quantize(Decimal('0.01'))


@login_required
@module_required('sales')
@require_POST
def close_daily(request):
    """Vue pour clôturer la journée et créer un DailyInventory"""
    import json
    from core.models.inventory_models import DailyInventory
    from core.models.accounting_models import DailyRecipe
    from core.models.settings_models import SystemSettings

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': _('Données invalides.')}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'success': False, 'message': _('Données invalides.')}, status=400)

    try:
        cash_in_hand = _parse_money(data.get('cash_in_hand', 0), _('Espèces en caisse'))
        cash_float = _parse_money(data.get('cash_float', 0), _('Fond de caisse'))
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    notes = str(data.get('notes') or '')[:2000]

    settings = SystemSettings.get_settings()
    tva_mode = getattr(settings, 'tva_accounting_mode', 'IMMEDIATE')
    enable_tva = getattr(settings, 'enable_tva_accounting', True)

    with transaction.atomic():
        # Ne JAMAIS créer une journée ici : on ferme celle qui est ouverte.
        current_daily = Daily.objects.select_for_update().filter(
            end_date__isnull=True, delete_at__isnull=True,
        ).order_by('-start_date').first()
        if not current_daily:
            return JsonResponse(
                {'success': False, 'message': _('Aucune journée ouverte à clôturer.')},
                status=409,
            )

        # Calculer les totaux
        total_sales = Sale.objects.filter(
            daily=current_daily, delete_at__isnull=True
        ).aggregate(total=Sum('total'))['total'] or 0
        total_expenses = DailyExpense.objects.filter(
            daily=current_daily, delete_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or 0
        total_recipes = DailyRecipe.objects.filter(
            daily=current_daily, delete_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        # TVA différée AVANT la fermeture, dans la même transaction : une vente
        # en erreur reste rattachée à une journée encore reprise par la commande
        # de rattrapage plutôt que perdue.
        tva_entries_created = 0
        if enable_tva and tva_mode == 'DEFERRED':
            tva_entries_created = AccountingService.record_deferred_tva_for_daily(current_daily)

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

        current_daily.end_date = timezone.now()
        current_daily.save(update_fields=['end_date'])

    return JsonResponse({
        'success': True,
        'message': _('La journée a été clôturée avec succès.'),
        'daily_inventory_id': daily_inventory.id,
        'tva_entries_created': tva_entries_created,
    })


@login_required
@module_required('settings')
def settings(request):
    """Vue de la page des paramètres système (instance singleton)."""
    from core.models.settings_models import SystemSettings

    settings_obj = SystemSettings.get_settings()

    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _('Paramètres enregistrés avec succès.'))
            return redirect('settings')
    else:
        form = SystemSettingsForm(instance=settings_obj)

    context = {
        'page_title': _('Paramètres'),
        'form': form,
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
                    _("Migration terminée avec succès ! %(total)s éléments créés.") % {'total': total}
                )
            except Exception as e:
                messages.error(request, _("Erreur lors de la migration : %(error)s") % {'error': str(e)})
    else:
        form = DataMigrationForm()

    context = {
        'page_title': _('Migration de données'),
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
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')
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
        'page_title': _('Journal comptable'),
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
    date_from = _clean_date_param(request, 'date_from')
    date_to = _clean_date_param(request, 'date_to')

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
        'page_title': _('Grand Livre'),
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
        'page_title': _('Balance générale'),
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
            '1': pgettext('classe comptable', 'Capitaux'),
            '2': pgettext('classe comptable', 'Immobilisations'),
            '3': pgettext('classe comptable', 'Stocks'),
            '4': pgettext('classe comptable', 'Tiers'),
            '5': pgettext('classe comptable', 'Trésorerie'),
            '6': pgettext('classe comptable', 'Charges'),
            '7': pgettext('classe comptable', 'Produits'),
        }
        class_label = class_names.get(class_num, _('Autres'))
        if class_num not in classes:
            classes[class_num] = {'label': class_label, 'accounts': []}
        classes[class_num]['accounts'].append(account)

    context = {
        'page_title': _('Plan comptable'),
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
    if format_type not in ('csv', 'txt'):
        return HttpResponse(_('Format inconnu'), status=400)
    
    # Définir le delimiter selon le format
    delimiter = ';' if format_type == 'csv' else '\t'
    
    accounts = Account.objects.filter(
        is_active=True, delete_at__isnull=True
    ).order_by('code')
    
    content_type = 'text/csv' if format_type == 'csv' else 'text/plain'
    response = HttpResponse(content_type=f'{content_type}; charset=utf-8')
    response.write('\ufeff')  # BOM UTF-8 pour Excel
    writer = _SafeCsvWriter(csv.writer(response, delimiter=delimiter))
    
    # En-tête
    filename = f"plan_comptable.{format_type}"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # En-têtes CSV
    writer.writerow([_('Code'), _('Libellé'), _('Type'), _('Compte Parent'), _('Description'), _('Actif')])
    
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


CHART_IMPORT_MAX_BYTES = 1 * 1024 * 1024   # 1 Mo
CHART_IMPORT_MAX_ROWS = 2000
# Comptes utilisés en dur par le moteur comptable : leur type et leur
# activation ne sont pas modifiables par import.
SYSTEM_ACCOUNT_CODES = frozenset({
    '12', '131', '139', '31', '401', '411', '4431', '4451', '521', '571', '585',
    '601', '65', '701', '75',
})


@login_required
@module_required('accounting')
@require_POST
def import_chart_of_accounts(request):
    """Import du plan comptable depuis CSV ou TXT (superusers uniquement)."""
    import io

    if not request.user.is_superuser:
        messages.error(request, _("L'import du plan comptable est réservé aux administrateurs."))
        return redirect('accounting_chart')
    
    file = request.FILES.get('file')
    if not file:
        messages.error(request, _("Aucun fichier sélectionné."))
        return redirect('accounting_chart')
    
    # Vérifier l'extension et la taille
    filename = file.name.lower()
    if not (filename.endswith('.csv') or filename.endswith('.txt')):
        messages.error(request, _("Le fichier doit être au format CSV ou TXT."))
        return redirect('accounting_chart')
    if file.size > CHART_IMPORT_MAX_BYTES:
        messages.error(request, _("Fichier trop volumineux (1 Mo maximum)."))
        return redirect('accounting_chart')
    
    delimiter = ';' if filename.endswith('.csv') else '\t'
    valid_types = ('ACTIF', 'PASSIF', 'CHARGE', 'PRODUIT')

    try:
        decoded = file.read(CHART_IMPORT_MAX_BYTES + 1).decode('utf-8-sig')
    except UnicodeDecodeError:
        messages.error(request, _("Le fichier doit être encodé en UTF-8."))
        return redirect('accounting_chart')

    reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
    next(reader, None)  # en-tête

    accounts_created = 0
    accounts_updated = 0
    errors = []

    try:
        # Tout ou rien : un import à moitié appliqué laisse un plan incohérent
        with transaction.atomic():
            for row_num, row in enumerate(reader, start=2):
                if row_num - 1 > CHART_IMPORT_MAX_ROWS:
                    raise ValueError(_("Trop de lignes (maximum %(max)s).") % {'max': CHART_IMPORT_MAX_ROWS})
                if not row or len(row) < 3:
                    continue

                code = row[0].strip()[:20]
                name = row[1].strip()[:255]
                account_type = row[2].strip().upper()
                if not code or not name:
                    errors.append(_("Ligne %(row)s: code ou libellé manquant") % {'row': row_num})
                    continue
                if account_type not in valid_types:
                    errors.append(_("Ligne %(row)s: Type de compte invalide '%(type)s'") % {'row': row_num, 'type': account_type})
                    continue

                parent_code = row[3].strip() if len(row) > 3 else ''
                description = row[4].strip() if len(row) > 4 else ''
                is_active = row[5].strip().lower() != 'non' if len(row) > 5 else True

                parent = None
                if parent_code:
                    parent = Account.objects.filter(code=parent_code, delete_at__isnull=True).first()
                    if parent is None:
                        errors.append(_("Ligne %(row)s: Compte parent '%(code)s' introuvable") % {'row': row_num, 'code': parent_code})
                        continue
                    if parent.code == code:
                        errors.append(_("Ligne %(row)s: un compte ne peut pas être son propre parent") % {'row': row_num})
                        continue

                defaults = {
                    'name': name,
                    'account_type': account_type,
                    'parent': parent,
                    'description': description,
                    'is_active': is_active,
                }
                existing = Account.objects.filter(code=code).first()
                if existing is not None and code in SYSTEM_ACCOUNT_CODES:
                    # Compte système : libellé/description/parent modifiables,
                    # jamais son type ni sa désactivation.
                    defaults['account_type'] = existing.account_type
                    defaults['is_active'] = True
                    if not is_active or account_type != existing.account_type:
                        errors.append(
                            _("Ligne %(row)s: le compte système %(code)s ne peut être ni désactivé ni changé de type (ignoré).") % {
                                'row': row_num, 'code': code,
                            }
                        )
                if existing is not None and existing.delete_at is not None:
                    # Réactivation explicite d'un compte supprimé
                    defaults['delete_at'] = None

                account, created = Account.objects.update_or_create(code=code, defaults=defaults)
                if created:
                    accounts_created += 1
                else:
                    accounts_updated += 1
    except ValueError as exc:
        messages.error(request, _("Import annulé : %(error)s") % {'error': exc})
        return redirect('accounting_chart')
    except Exception:
        logger.exception("Erreur lors de l'import du plan comptable")
        messages.error(request, _("Import annulé : erreur interne. Aucune modification n'a été enregistrée."))
        return redirect('accounting_chart')

    if accounts_created > 0:
        messages.success(request, _("%(count)s compte(s) créé(s).") % {'count': accounts_created})
    if accounts_updated > 0:
        messages.success(request, _("%(count)s compte(s) mis à jour.") % {'count': accounts_updated})
    if errors:
        for error in errors[:10]:  # Limiter à 10 erreurs affichées
            messages.warning(request, error)
        if len(errors) > 10:
            messages.warning(request, _("... et %(count)s erreur(s) supplémentaire(s).") % {'count': len(errors) - 10})

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
    
    MAX_LINES = 50
    MAX_AMOUNT = Decimal('9999999999999.99')  # max_digits=15

    if request.method == 'POST':
        from decimal import InvalidOperation
        form = JournalEntryForm(request.POST)

        # Récupérer les lignes (nombre borné, montants >= 0, comptes actifs)
        try:
            line_count = int(request.POST.get('line_count', 2))
        except (TypeError, ValueError):
            line_count = 0
        line_count = max(0, min(line_count, MAX_LINES))
        active_account_ids = set(accounts.values_list('id', flat=True))

        lines_data = []
        errors = []
        
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        
        for i in range(line_count):
            account_id = request.POST.get(f'account_{i}')
            debit = (request.POST.get(f'debit_{i}') or '0').replace(',', '.').strip()
            credit = (request.POST.get(f'credit_{i}') or '0').replace(',', '.').strip()
            line_desc = (request.POST.get(f'line_desc_{i}') or '')[:255]
            
            if not account_id:
                continue

            try:
                account_id = int(account_id)
                debit_val = Decimal(debit or '0')
                credit_val = Decimal(credit or '0')
            except (ValueError, TypeError, InvalidOperation):
                errors.append(_("Ligne %(line)s: compte ou montant invalide.") % {'line': i + 1})
                continue

            if account_id not in active_account_ids:
                errors.append(_("Ligne %(line)s: compte inconnu ou inactif.") % {'line': i + 1})
                continue
            if not debit_val.is_finite() or not credit_val.is_finite():
                errors.append(_("Ligne %(line)s: montant invalide.") % {'line': i + 1})
                continue
            if debit_val < 0 or credit_val < 0:
                errors.append(_("Ligne %(line)s: les montants ne peuvent pas être négatifs.") % {'line': i + 1})
                continue
            if debit_val > MAX_AMOUNT or credit_val > MAX_AMOUNT:
                errors.append(_("Ligne %(line)s: montant trop élevé.") % {'line': i + 1})
                continue

            # Au moins un montant doit être positif
            if debit_val == 0 and credit_val == 0:
                continue
                
            # Les deux ne peuvent pas être positifs
            if debit_val > 0 and credit_val > 0:
                errors.append(_("Ligne %(line)s: Un compte ne peut pas avoir à la fois un débit et un crédit.") % {'line': i + 1})
                continue
                
            total_debit += debit_val
            total_credit += credit_val
            
            lines_data.append({
                'account_id': account_id,
                'debit': debit_val,
                'credit': credit_val,
                'description': line_desc
            })
        
        # Validation
        if not form.is_valid():
            errors.extend([f"{k}: {v[0]}" for k, v in form.errors.items()])
        
        if not lines_data:
            errors.append(_("Veuillez saisir au moins une ligne avec un montant."))
        
        if total_debit != total_credit:
            errors.append(_("L'écriture n'est pas équilibrée. Total débit: %(debit)s, Total crédit: %(credit)s") % {
                'debit': total_debit, 'credit': total_credit,
            })
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Créer l'écriture : en-tête + lignes dans une seule transaction
            try:
                with transaction.atomic():
                    exercise = ExerciseService.get_or_create_current_exercise()
                    entry = AccountingService._create_entry(
                        'OD',  # OD = Opérations Diverses
                        date=form.cleaned_data['date'],
                        description=form.cleaned_data['description'],
                        journal='OD',
                        exercise=exercise,
                        is_validated=True,
                    )
                    JournalEntryLine.objects.bulk_create([
                        JournalEntryLine(
                            entry=entry,
                            account_id=line_data['account_id'],
                            debit=line_data['debit'],
                            credit=line_data['credit'],
                            description=line_data['description'],
                        )
                        for line_data in lines_data
                    ])
                
                messages.success(request, _("Écriture %(reference)s créée avec succès!") % {'reference': entry.reference})
                return redirect('accounting_journal')
                
            except Exception:
                logger.exception("Erreur lors de la création d'une écriture manuelle")
                messages.error(request, _("Erreur interne lors de la création de l'écriture. Rien n'a été enregistré."))
    else:
        form = JournalEntryForm()
    
    context = {
        'page_title': _('Nouvelle écriture comptable'),
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
        'page_title': _('Ventes à crédit'),
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
        messages.warning(request, _('Cette vente à crédit est déjà entièrement payée.'))
        return redirect('credit_sales')

    if request.method == 'POST':
        form = PaymentForm(request.POST, credit_sale=credit_sale)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Re-lire sous verrou : deux paiements simultanés ne
                    # peuvent pas dépasser le reste dû.
                    credit_sale = CreditSale.objects.select_for_update().select_related('sale').get(
                        pk=credit_sale.pk, delete_at__isnull=True,
                    )
                    amount = form.cleaned_data['amount']
                    if credit_sale.is_fully_paid or amount > credit_sale.amount_remaining:
                        raise ValueError(
                            _("Le montant dépasse le solde restant (%(amount)s FCFA).") % {
                                'amount': f'{credit_sale.amount_remaining:,.0f}',
                            }
                        )

                    payment = form.save(commit=False)
                    payment.credit_sale = credit_sale
                    payment.staff = request.user
                    daily = DailyService.get_or_create_active_daily()
                    payment.daily = daily
                    payment.save()

                    credit_sale.amount_paid += payment.amount
                    credit_sale.amount_remaining -= payment.amount
                    if credit_sale.amount_remaining <= 0:
                        credit_sale.amount_remaining = 0
                        credit_sale.is_fully_paid = True
                        credit_sale.sale.is_paid = True
                        credit_sale.sale.save(update_fields=['is_paid'])
                    credit_sale.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])

                    # Écriture comptable (dans la même transaction : un
                    # encaissement sans écriture n'est plus possible)
                    AccountingService.record_credit_payment(
                        payment=payment,
                        daily=daily,
                        exercise=daily.exercise,
                    )
            except ValueError as exc:
                messages.error(request, str(exc))
            except Exception:
                logger.exception("Erreur lors de l'enregistrement d'un paiement client")
                messages.error(request, _("Erreur interne : le paiement n'a pas été enregistré."))
            else:
                messages.success(
                    request,
                    _('Paiement de %(amount)s FCFA enregistré. Solde restant : %(remaining)s FCFA.') % {
                        'amount': f'{payment.amount:,.0f}',
                        'remaining': f'{credit_sale.amount_remaining:,.0f}',
                    }
                )
                return redirect('credit_sales')
    else:
        form = PaymentForm(credit_sale=credit_sale)

    # Historique des paiements sur cette vente
    payments = credit_sale.payments.filter(delete_at__isnull=True).order_by('-payment_date')

    context = {
        'page_title': _('Paiement – Vente #%(id)s') % {'id': credit_sale.sale_id},
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
    supplier_id = _clean_int_param(request, 'supplier')

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
        'page_title': _('Paiements fournisseurs'),
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

            # Écriture comptable. Une erreur ne bloque pas le paiement mais
            # n'est plus silencieuse : elle est journalisée et le paiement
            # est marqué « à rejouer » (``manage.py replay_accounting``).
            exercise = daily.exercise if daily else ExerciseService.get_or_create_current_exercise()
            AccountingService.safe_record_supplier_payment(
                supplier_payment=payment,
                daily=daily,
                exercise=exercise,
            )

            messages.success(
                request,
                _('Paiement de %(amount)s FCFA à %(supplier)s enregistré.') % {
                    'amount': f'{payment.amount:,.0f}', 'supplier': payment.supplier.name,
                }
            )
            return redirect('supplier_payments')
    else:
        form = SupplierPaymentForm()

    context = {
        'page_title': _('Nouveau paiement fournisseur'),
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
        messages.warning(request, _('Cet approvisionnement n\'est pas un achat à crédit.'))
        return redirect('supplies')

    def _get_or_create_credit_supply(locked=False):
        qs = CreditSupply.objects.select_for_update() if locked else CreditSupply.objects
        credit = qs.filter(supply=supply, delete_at__isnull=True).first()
        if credit is None and locked:
            # Créé uniquement dans le flux POST (jamais sur un simple GET) en
            # tenant compte des paiements déjà enregistrés sur cet achat.
            already_paid = SupplierPayment.objects.filter(
                supply=supply, delete_at__isnull=True,
            ).aggregate(total=Sum('amount'))['total'] or 0
            credit = CreditSupply.objects.create(
                supply=supply,
                amount_paid=already_paid,
                amount_remaining=max((supply.total_price or 0) - already_paid, 0),
                is_fully_paid=(supply.total_price or 0) - already_paid <= 0,
            )
        return credit

    credit_supply = _get_or_create_credit_supply()
    if credit_supply is not None and credit_supply.is_fully_paid:
        messages.warning(request, _('Cet approvisionnement est déjà payé.'))
        return redirect('supplies')
    amount_remaining = (
        credit_supply.amount_remaining if credit_supply is not None else (supply.total_price or 0)
    )

    if request.method == 'POST':
        # Le fournisseur est imposé : celui de l'approvisionnement
        post_data = request.POST.copy()
        post_data['supplier'] = supply.supplier_id
        form = SupplierPaymentForm(post_data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    credit_supply = _get_or_create_credit_supply(locked=True)
                    amount = form.cleaned_data['amount']
                    if credit_supply.is_fully_paid or amount > credit_supply.amount_remaining:
                        raise ValueError(
                            _("Le montant dépasse le reste dû (%(amount)s FCFA).") % {
                                'amount': f'{credit_supply.amount_remaining:,.0f}',
                            }
                        )

                    payment = form.save(commit=False)
                    payment.supplier = supply.supplier
                    payment.supply = supply
                    payment.staff = request.user
                    daily = DailyService.get_or_create_active_daily()
                    payment.daily = daily
                    payment.save()

                    credit_supply.amount_paid += payment.amount
                    credit_supply.amount_remaining -= payment.amount
                    if credit_supply.amount_remaining <= 0:
                        credit_supply.amount_remaining = 0
                        credit_supply.is_fully_paid = True
                        supply.is_paid = True
                        supply.save(update_fields=['is_paid'])
                    credit_supply.save(update_fields=['amount_paid', 'amount_remaining', 'is_fully_paid'])

                    AccountingService.record_supplier_payment(
                        supplier_payment=payment,
                        daily=daily,
                        exercise=daily.exercise,
                    )
            except ValueError as exc:
                messages.error(request, str(exc))
            except Exception:
                logger.exception("Erreur lors de l'enregistrement d'un paiement fournisseur")
                messages.error(request, _("Erreur interne : le paiement n'a pas été enregistré."))
            else:
                messages.success(
                    request,
                    _('Paiement de %(amount)s FCFA pour %(product)s enregistré. Restant: %(remaining)s FCFA') % {
                        'amount': f'{payment.amount:,.0f}',
                        'product': supply.product.name,
                        'remaining': f'{credit_supply.amount_remaining:,.0f}',
                    }
                )
                return redirect('supplies')
    else:
        # Pré-remplir le formulaire avec le montant restant
        initial_data = {
            'amount': amount_remaining,
            'supplier': supply.supplier,
        }
        form = SupplierPaymentForm(initial=initial_data)
    form.fields['supplier'].disabled = True
    if credit_supply is None:
        # Vue en lecture : objet non persisté pour l'affichage
        credit_supply = CreditSupply(
            supply=supply, amount_paid=0, amount_remaining=amount_remaining, is_fully_paid=False,
        )

    # Historique des paiements pour ce fournisseur
    payments = SupplierPayment.objects.filter(
        supplier=supply.supplier, delete_at__isnull=True
    ).order_by('-payment_date')[:5]

    context = {
        'page_title': _('Paiement – %(product)s') % {'product': supply.product.name},
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
        'page_title': _('Factures'),
        'page_obj': page_obj,
        'invoices': page_obj.object_list,
        'current_search': search,
        'current_status': status_filter,
        'total_count': paginator.count,
    }
    return render(request, 'core/accounting/invoices.html', context)


@login_required
@module_required('treasury')
@require_POST
def generate_invoice(request, sale_id):
    """Génère une facture pour une vente (POST : action qui crée une donnée)."""
    with transaction.atomic():
        sale = get_object_or_404(
            Sale.objects.select_for_update(), id=sale_id, delete_at__isnull=True,
        )
        existing = Invoice.objects.filter(sale=sale).first()
        if existing is not None:
            if existing.delete_at is None:
                messages.info(request, _('Facture %(number)s existe déjà pour cette vente.') % {'number': existing.invoice_number})
                return redirect('invoices')
            # Une facture annulée (soft-delete) occupe déjà la relation 1-1 :
            # on la réactive avec un nouveau numéro plutôt que de planter.
            existing.delete_at = None
            existing.invoice_number = Invoice.generate_invoice_number()
            existing.invoice_date = timezone.now().date()
            existing.status = 'PAID' if sale.is_paid else 'SENT'
            existing.save()
            invoice = existing
        else:
            credit_info = getattr(sale, 'credit_info', None)
            invoice = Invoice.objects.create(
                sale=sale,
                invoice_number=Invoice.generate_invoice_number(),
                invoice_date=timezone.now().date(),
                due_date=credit_info.due_date if credit_info else None,
                status='PAID' if sale.is_paid else 'SENT',
            )

    messages.success(request, _('Facture %(number)s générée avec succès.') % {'number': invoice.invoice_number})
    return redirect('invoices')


@login_required
@module_required('treasury')
def invoice_pdf(request, pk):
    """Télécharge une facture au format PDF."""
    from core.models.settings_models import SystemSettings
    from core.services.invoice_pdf_service import InvoicePdfService

    invoice = get_object_or_404(
        Invoice.objects.select_related('sale', 'sale__client').filter(delete_at__isnull=True),
        pk=pk,
    )
    settings_obj = SystemSettings.get_settings()
    pdf_bytes = InvoicePdfService.build_pdf(invoice, settings_obj)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
    return response


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
        'page_title': _('Trésorerie'),
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
        'page_title': _('Compte de résultat'),
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
        'page_title': _('Bilan comptable'),
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


    context = {
        'page_title': _("Balance âgée — %(title)s") % {'title': data['title']},
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
        'page_title': _('Marge par produit'),
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
    writer = _SafeCsvWriter(csv.writer(response, delimiter=';'))

    if report_type == 'income_statement':
        response['Content-Disposition'] = 'attachment; filename="compte_de_resultat.csv"'
        data = AccountingService.get_income_statement(exercise)
        writer.writerow([_('Compte de résultat'), _('Exercice %(exercise)s') % {'exercise': exercise}])
        writer.writerow([])
        writer.writerow([_('PRODUITS')])
        writer.writerow([_('Code'), _('Intitulé'), _('Montant')])
        for item in data['produits']:
            writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', _('TOTAL PRODUITS'), str(data['total_produits'])])
        writer.writerow([])
        writer.writerow([_('CHARGES')])
        writer.writerow([_('Code'), _('Intitulé'), _('Montant')])
        for item in data['charges']:
            writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', _('TOTAL CHARGES'), str(data['total_charges'])])
        writer.writerow([])
        writer.writerow(['', _('RÉSULTAT NET'), str(data['resultat_net'])])

    elif report_type == 'balance_sheet':
        response['Content-Disposition'] = 'attachment; filename="bilan_comptable.csv"'
        data = AccountingService.get_balance_sheet(exercise)
        writer.writerow([_('Bilan comptable'), _('Exercice %(exercise)s') % {'exercise': exercise}])
        writer.writerow([])
        writer.writerow([_('ACTIF')])
        writer.writerow([_('Code'), _('Intitulé'), _('Montant')])
        for section in [data['actif_immobilise'], data['actif_circulant'], data['tresorerie_actif']]:
            for item in section:
                writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        writer.writerow(['', _('TOTAL ACTIF'), str(data['total_actif'])])
        writer.writerow([])
        writer.writerow([_('PASSIF')])
        writer.writerow([_('Code'), _('Intitulé'), _('Montant')])
        for section in [data['capitaux'], data['dettes'], data['tresorerie_passif']]:
            for item in section:
                writer.writerow([item['account'].code, item['account'].name, str(item['balance'])])
        if data['resultat_net'] > 0:
            writer.writerow(['', _('Résultat de l\'exercice'), str(data['resultat_net'])])
        writer.writerow(['', _('TOTAL PASSIF'), str(data['total_passif'])])

    elif report_type == 'product_margins':
        response['Content-Disposition'] = 'attachment; filename="marges_produits.csv"'
        data = AccountingService.get_product_margins(exercise)
        writer.writerow([_('Marge par produit'), _('Exercice %(exercise)s') % {'exercise': exercise}])
        writer.writerow([])
        writer.writerow([_('Produit'), _('Qté vendue'), _('CA (FCFA)'), _('Prix achat'), _('Coût total'), _('Marge'), _('Marge %')])
        for item in data['items']:
            writer.writerow([
                item['product'].name, item['qty_sold'],
                str(item['revenue']), str(item['purchase_price']),
                str(item['cost']), str(item['margin']),
                f"{item['margin_pct']:.1f}%",
            ])
        writer.writerow([])
        writer.writerow([_('TOTAUX'), '', str(data['total_ca']), '',
                         str(data['total_cost']), str(data['total_margin']),
                         f"{data['total_margin_pct']:.1f}%"])

    elif report_type == 'aged_balance':
        balance_type = request.GET.get('type', 'client')
        if balance_type not in ('client', 'supplier'):
            return HttpResponse(_('Type de balance inconnu'), status=400)
        response['Content-Disposition'] = f'attachment; filename="balance_agee_{balance_type}.csv"'
        data = AccountingService.get_aged_balance(balance_type, exercise)
        writer.writerow([data['title'], _('Exercice %(exercise)s') % {'exercise': exercise}])
        writer.writerow([])
        writer.writerow([_('Référence'), _('Tiers'), _('Date'), _('Échéance'), _('Jours'), _('Tranche'), _('Montant')])
        for item in data['items']:
            writer.writerow([
                item['reference'], item['tiers'],
                item['date'].strftime('%d/%m/%Y') if item['date'] else '',
                item['due_date'].strftime('%d/%m/%Y') if item['due_date'] else '',
                item['age_days'], item['tranche'], str(item['amount']),
            ])
        writer.writerow([])
        writer.writerow(['', '', '', '', '', _('TOTAL'), str(data['grand_total'])])

    else:
        return HttpResponse(_('Type de rapport inconnu'), status=400)

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
        'page_title': _('Déclaration de TVA'),
        'exercise': exercise,
        **data,
    }
    return render(request, 'core/accounting/vat_declaration.html', context)


@login_required
@module_required('accounting')
def bank_reconciliation(request):
    """Rapprochement bancaire."""
    account_code = request.GET.get('account', '521')
    date_start = _clean_date_param(request, 'date_start', default=None)
    date_end = _clean_date_param(request, 'date_end', default=None)

    # Convertir les dates
    from datetime import datetime as dt
    d_start = dt.strptime(date_start, '%Y-%m-%d').date() if date_start else None
    d_end = dt.strptime(date_end, '%Y-%m-%d').date() if date_end else None

    try:
        data = AccountingService.get_bank_reconciliation(account_code, d_start, d_end)
    except Account.DoesNotExist:
        from django.http import Http404
        raise Http404(_("Compte bancaire introuvable"))

    # Comptes bancaires disponibles pour le sélecteur
    bank_accounts = Account.objects.filter(
        code__in=['521', '585'], delete_at__isnull=True
    )

    context = {
        'page_title': _('Rapprochement bancaire'),
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
        return JsonResponse({'error': _('Méthode non autorisée')}, status=405)

    statement_id = request.POST.get('statement_id')
    entry_line_id = request.POST.get('entry_line_id')

    if not statement_id or not entry_line_id:
        return JsonResponse({'error': _('Paramètres manquants')}, status=400)

    try:
        stmt = AccountingService.reconcile_statement(
            int(statement_id), int(entry_line_id), user=request.user
        )
        return JsonResponse({
            'success': True,
            'message': _('Ligne rapprochée avec succès'),
        })
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception:
        logger.exception("Erreur de rapprochement bancaire")
        return JsonResponse({'error': _('Rapprochement impossible.')}, status=400)


@login_required
@module_required('accounting')
def unreconcile_entry(request):
    """Annuler le rapprochement d'une ligne (POST AJAX)."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': _('Méthode non autorisée')}, status=405)

    statement_id = request.POST.get('statement_id')
    if not statement_id:
        return JsonResponse({'error': _('Paramètre manquant')}, status=400)

    try:
        AccountingService.unreconcile_statement(int(statement_id))
        return JsonResponse({'success': True, 'message': _('Rapprochement annulé')})
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception:
        logger.exception("Erreur d'annulation de rapprochement bancaire")
        return JsonResponse({'error': _("Annulation du rapprochement impossible.")}, status=400)


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
        'page_title': _("Clôture d'exercice"),
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

    # Ne jamais créer un exercice vide pour le clôturer aussitôt
    exercise = ExerciseService.get_current_exercise()
    if exercise is None:
        messages.error(request, _("Aucun exercice ouvert à clôturer."))
        return redirect('exercise_closing')

    # L'utilisateur confirme l'exercice affiché : refuse si un autre est ouvert
    confirmed_id = request.POST.get('exercise_id')
    if confirmed_id and str(exercise.pk) != str(confirmed_id):
        messages.error(request, _("L'exercice affiché n'est plus l'exercice ouvert. Rechargez la page."))
        return redirect('exercise_closing')

    try:
        # Clôture + réouverture dans UNE transaction : pas d'exercice clos
        # sans successeur, pas d'à-nouveaux dupliqués.
        with transaction.atomic():
            closing = AccountingService.close_exercise(exercise, user=request.user)
            AccountingService.open_new_exercise(closing, user=request.user)
        messages.success(
            request,
            _("Exercice clôturé avec succès. Résultat : %(result)s FCFA. Nouvel exercice créé.") % {
                'result': closing.result_amount,
            }
        )
    except ValueError as e:
        messages.error(request, str(e))
    except Exception:
        logger.exception("Erreur lors de la clôture de l'exercice #%s", exercise.pk)
        messages.error(request, _("Erreur interne lors de la clôture. Aucune modification n'a été enregistrée."))

    return redirect('exercise_closing')
