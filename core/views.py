from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F, Sum
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from core.models.sale_models import Sale
from core.models.user_models import Client, Supplier, CustomUser
from core.models.accounting_models import Daily, DailyExpense, ExpenseType, Exercise
from core.models.product_models import Product, Category, Gamme, Rayon
from core.models.inventory_models import Supply, Inventory, InventorySnapshot
from core.services.daily_service import DailyService
from core.forms import SupplyForm, ExpenseForm, ClientForm, SupplierForm, InventoryForm
from core.services.excercise_service import ExerciseService

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
def sales_history(request):
    """Vue de l'historique complet des ventes avec filtres et pagination"""
    from django.db.models import Sum

    search = request.GET.get('search', '').strip()
    client_id = request.GET.get('client', '')
    staff_id = request.GET.get('staff', '')
    sale_type = request.GET.get('type', '')
    payment_status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)

    queryset = Sale.objects.filter(
        delete_at__isnull=True,
    ).select_related('client', 'staff', 'daily')

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


INVENTORY_PER_PAGE_CHOICES = [10, 25, 50, 100]


@login_required
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
        'page_title': 'Utilisateurs',
        'current_tab': tab,
        'current_search': search,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'total_count': paginator.count,
    }
    return render(request, 'core/contacts.html', context)


@login_required
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
def add_supplier(request):
    """Vue pour ajouter un nouveau fournisseur"""
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Fournisseur "{form.cleaned_data["firstname"]}" créé avec succès.')
            return redirect('/contacts/?tab=suppliers')
    else:
        form = SupplierForm()

    context = {
        'page_title': 'Nouveau fournisseur',
        'form': form,
        'form_title': 'Nouveau fournisseur',
        'form_subtitle': 'Créer un nouveau fournisseur',
        'back_url': 'contacts',
        'back_tab': 'suppliers',
    }
    return render(request, 'core/contacts_form.html', context)


@login_required
def edit_supplier(request, pk):
    """Vue pour modifier un fournisseur"""
    supplier = get_object_or_404(Supplier, pk=pk, delete_at__isnull=True)

    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f'Fournisseur "{supplier.get_full_name()}" modifié avec succès.')
            return redirect('/contacts/?tab=suppliers')
    else:
        form = SupplierForm(instance=supplier)

    context = {
        'page_title': f'Modifier {supplier.get_full_name()}',
        'form': form,
        'form_title': 'Modifier le fournisseur',
        'form_subtitle': f'Modifier les informations de {supplier.get_full_name()}',
        'back_url': 'contacts',
        'back_tab': 'suppliers',
    }
    return render(request, 'core/contacts_form.html', context)


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
def add_supply(request):
    """Vue pour ajouter un nouvel approvisionnement"""
    if request.method == 'POST':
        form = SupplyForm(request.POST)
        if form.is_valid():
            supply = form.save(commit=False)
            supply.staff = request.user
            supply.daily = DailyService.get_or_create_active_daily()
            supply.total_price = supply.quantity * supply.unit_price
            supply.save()

            # Mettre à jour le stock du produit
            product = supply.product
            product.stock = (product.stock or 0) + supply.quantity
            # Mettre à jour le dernier prix d'achat
            product.last_purchase_price = supply.unit_price
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
                    'unit_price': float(supply.unit_price),
                    'total_price': float(supply.total_price),
                })

            messages.success(request, f'Approvisionnement de {supply.quantity} x "{product.name}" enregistré avec succès.')
            return redirect('supplies')
    else:
        form = SupplyForm()

    context = {
        'page_title': 'Nouvel approvisionnement',
        'form': form,
    }
    return render(request, 'core/supplies_add.html', context)


@login_required
def expenses(request):
    """Vue de la page des dépenses quotidiennes avec pagination et filtres"""
    search = request.GET.get('search', '').strip()
    expense_type_id = request.GET.get('expense_type', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)

    queryset = DailyExpense.objects.filter(
        delete_at__isnull=True,
    ).select_related('expense_type', 'staff', 'daily', 'exercise')

    if search:
        queryset = queryset.filter(
            Q(description__icontains=search) | Q(expense_type__name__icontains=search)
        )
    if expense_type_id:
        queryset = queryset.filter(expense_type_id=expense_type_id)
    if date_from:
        queryset = queryset.filter(create_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(create_at__date__lte=date_to)

    queryset = queryset.order_by('-create_at')

    # Total des dépenses filtrées
    from django.db.models import Sum
    total_expenses = queryset.aggregate(total=Sum('amount'))['total'] or 0

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)

    expense_types = ExpenseType.objects.filter(delete_at__isnull=True).order_by('name')

    context = {
        'page_title': 'Dépenses',
        'page_obj': page_obj,
        'expenses': page_obj.object_list,
        'expense_types': expense_types,
        'current_search': search,
        'current_expense_type': expense_type_id,
        'current_date_from': date_from,
        'current_date_to': date_to,
        'total_count': paginator.count,
        'total_expenses': total_expenses,
    }
    return render(request, 'core/expenses.html', context)


@login_required
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

            messages.success(request, f'Dépense de {expense.amount:,.0f} FCFA enregistrée avec succès.')
            return redirect('expenses')
    else:
        # Pré-remplir les champs si des paramètres GET sont présents
        initial_data = {}

        if request.GET.get('amount'):
            initial_data['amount'] = request.GET.get('amount')

        if request.GET.get('description'):
            initial_data['description'] = request.GET.get('description')

        form = ExpenseForm(initial=initial_data)

    context = {
        'page_title': 'Nouvelle dépense',
        'form': form,
    }
    return render(request, 'core/expenses_add.html', context)


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
