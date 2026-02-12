from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q

from core.services.daily_service import DailyService
from .models import Product, Sale, ProductImage, Daily
from .serializers import ProductSearchSerializer, SaleCreateSerializer, SaleSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_products(request):
    """
    API pour rechercher des produits
    Paramètres:
        - q: terme de recherche (nom, code)
    """
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return Response({
            'error': 'Le terme de recherche doit contenir au moins 2 caractères'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Rechercher dans le nom et code
    products = Product.objects.filter(
        Q(name__icontains=query) |
        Q(code__icontains=query)
    ).filter(stock__gt=0)[:10]  # Limiter à 10 résultats
    
    serializer = ProductSearchSerializer(products, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_sale(request):
    """
    API pour créer une vente
    Body:
        {
            "client_id": 1 (optionnel),
            "is_credit": false,
            "due_date": "2024-12-31" (optionnel),
            "items": [
                {
                    "product_id": 1,
                    "quantity": 2,
                    "unit_price": 5000
                }
            ]
        }
    """
    serializer = SaleCreateSerializer(data=request.data, context={'request': request})

    if serializer.is_valid():
        sale = serializer.save()
        sale_serializer = SaleSerializer(sale)
        return Response({
            'message': 'Vente créée avec succès',
            'sale': sale_serializer.data
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sale_details(request, sale_id):
    """
    API pour obtenir les détails d'une vente
    """
    try:
        sale = Sale.objects.get(id=sale_id)
    except Sale.DoesNotExist:
        return Response({
            'error': 'Vente introuvable'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Récupérer les articles de la vente
    items = sale.sale_products.all()
    
    items_data = [{
        'product_name': item.product.name,
        'product_code': item.product.code,
        'quantity': item.quantity,
        'unit_price': float(item.unit_price),
        'subtotal': float(item.unit_price * item.quantity)
    } for item in items]
    
    sale_data = {
        'id': sale.id,
        'client_name': str(sale.client),
        'staff_name': str(sale.staff),
        'total': float(sale.total),
        'is_credit': sale.is_credit,
        'is_paid': sale.is_paid,
        'create_at': sale.create_at,
        'items': items_data
    }

    if sale.is_credit:
        credit_sale = sale.get_related_credit_sale()
        if credit_sale: 
            sale_data['credit_info'] = {
                'amount_paid': float(credit_sale.amount_paid),
                'amount_remaining': float(credit_sale.amount_remaining),
                'due_date': credit_sale.due_date
            }

    
    return Response(sale_data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_details(request, product_id):
    """
    API pour obtenir les détails complets d'un produit
    """
    try:
        product = Product.objects.select_related(
            'category', 'gamme', 'rayon', 'grammage_type'
        ).get(id=product_id)
    except Product.DoesNotExist:
        return Response({
            'error': 'Produit introuvable'
        }, status=status.HTTP_404_NOT_FOUND)

    # Récupérer les images du produit
    images = ProductImage.objects.filter(product=product)
    images_data = [{
        'id': img.id,
        'url': img.image.url if img.image else None,
        'is_main': img.is_main
    } for img in images]

    product_data = {
        'id': product.id,
        'code': product.code,
        'name': product.name,
        'description': product.description,
        'brand': product.brand,
        'color': product.color,
        'stock': product.stock,
        'stock_limit': product.stock_limit,
        'max_salable_price': float(product.max_salable_price) if product.max_salable_price else None,
        'actual_price': float(product.actual_price) if product.actual_price else None,
        'is_price_reducible': product.is_price_reducible,
        'grammage': product.grammage,
        'exp_alert_period': product.exp_alert_period,
        'category': {
            'id': product.category.id,
            'name': product.category.name,
            'description': product.category.description
        } if product.category else None,
        'gamme': {
            'id': product.gamme.id,
            'name': product.gamme.name,
            'description': product.gamme.description
        } if product.gamme else None,
        'rayon': {
            'id': product.rayon.id,
            'name': product.rayon.name,
            'description': product.rayon.description
        } if product.rayon else None,
        'grammage_type': {
            'id': product.grammage_type.id,
            'name': product.grammage_type.name
        } if product.grammage_type else None,
        'images': images_data,
        'create_at': product.create_at,
        'delete_at': product.delete_at
    }

    return Response(product_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_sales(request):
    """
    API pour rechercher des ventes du Daily en cours
    Paramètres:
        - q: terme de recherche (client, staff, montant, produits)
    """
    query = request.GET.get('q', '').strip()

    # Récupérer le Daily actif
    current_daily = DailyService().get_or_create_active_daily()

    if not current_daily:
        return Response([])

    # Filtrer les ventes du Daily en cours
    sales = Sale.objects.select_related('client', 'staff', 'daily').filter(
        delete_at__isnull=True,
        daily=current_daily
    )

    # Appliquer la recherche si un terme est fourni
    if query:
        sales = sales.filter(
            Q(client__firstname__icontains=query) |
            Q(client__lastname__icontains=query) |
            Q(staff__first_name__icontains=query) |
            Q(staff__last_name__icontains=query) |
            Q(total__icontains=query) |
            Q(id__icontains=query) |
            Q(sale_products__product__name__icontains=query) |
            Q(sale_products__product__code__icontains=query)
        ).distinct()  # distinct() pour éviter les doublons dus aux jointures

    sales = sales.order_by('-create_at')

    # Sérialiser les résultats
    sales_data = []
    for sale in sales:
        sale_data = {
            'id': sale.id,
            'client_name': f"{sale.client.firstname} {sale.client.lastname}" if sale.client else "Client de passage",
            'staff_name': f"{sale.staff.first_name} {sale.staff.last_name}" if sale.staff else "N/A",
            'total': float(sale.total) if sale.total else 0,
            'is_credit': sale.is_credit,
            'is_paid': sale.is_paid,
            'create_at': sale.create_at.strftime('%Y-%m-%d %H:%M:%S') if sale.create_at else None,
        }
        sales_data.append(sale_data)

    return Response(sales_data)


