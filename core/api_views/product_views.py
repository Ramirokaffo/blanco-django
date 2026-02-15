"""
Vues pour la gestion des produits.
Correspond aux anciens endpoints Flask:
  - GET  /get_product_list/<page>/<count>
  - GET  /search_product
  - GET  /get_product_by_id/<product_id>
  - GET  /get_product_by_code/<product_code>
  - GET  /get_product_by_name/<product_name>
  - GET  /image/<folder>/<image>
  - POST /create_product
"""

import mimetypes

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.serializers.product_serializers import (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductCreateSerializer,
)
from core.services.product_service import ProductService
from core.services.daily_service import DailyService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_list(request):
    """
    Liste paginée des produits.
    Ancien Flask: GET /get_product_list/<page>/<count>
    """
    page = int(request.GET.get('page', 1))
    count = int(request.GET.get('count', 20))
    products = ProductService.get_product_list(page=page, count=count)
    serializer = ProductListSerializer(products, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_products(request):
    """
    Rechercher des produits par nom ou code.
    Ancien Flask: GET /search_product?search_input=...&page=...&count=...
    """
    search_input = request.GET.get('search_input', request.GET.get('q', '')).strip()
    page = int(request.GET.get('page', 1))
    count = int(request.GET.get('count', 20))

    if len(search_input) < 2:
        return Response({
            'error': 'Le terme de recherche doit contenir au moins 2 caractères'
        }, status=status.HTTP_400_BAD_REQUEST)

    products = ProductService.search_products(search_input, page=page, count=count)
    serializer = ProductListSerializer(products, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_by_id(request, product_id):
    """
    Détails d'un produit par ID.
    Ancien Flask: GET /get_product_by_id/<product_id>
    """
    product = ProductService.get_by_id(product_id)
    if not product:
        return Response(None, status=status.HTTP_404_NOT_FOUND)
    serializer = ProductDetailSerializer(product, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_by_code(request, product_code):
    """
    Détails d'un produit par code.
    Ancien Flask: GET /get_product_by_code/<product_code>
    """
    product = ProductService.get_by_code(product_code)
    if not product:
        return Response(None)

    return_all = request.GET.get('return_all', '0')
    if return_all == '1':
        serializer = ProductDetailSerializer(product, context={'request': request})
    else:
        serializer = ProductDetailSerializer(product, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_by_name(request, product_name):
    """
    Détails d'un produit par nom.
    Ancien Flask: GET /get_product_by_name/<product_name>
    """
    product = ProductService.get_by_name(product_name)
    if not product:
        return Response(None)
    serializer = ProductDetailSerializer(product, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_product(request):
    """
    Créer un produit.
    Ancien Flask: POST /create_product
    """
    serializer = ProductCreateSerializer(data=request.data)
    if serializer.is_valid():
        images = request.FILES.getlist('images')
        daily = DailyService.get_or_create_active_daily()
        product = ProductService.create_product(
            validated_data=serializer.validated_data,
            images=images,
            staff=request.user,
            daily=daily,
        )
        detail_serializer = ProductDetailSerializer(product, context={'request': request})
        return Response({
            'status': 1,
            'product': detail_serializer.data,
        }, status=status.HTTP_201_CREATED)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_image(request, folder, image):
    """
    Servir une image depuis le dossier media.
    Ancien Flask: GET /image/<folder>/<image>
    """
    path = ProductService.get_image_path(folder, image)
    if not path:
        raise Http404("Image introuvable.")
    content_type, _ = mimetypes.guess_type(path)
    return FileResponse(open(path, 'rb'), content_type=content_type or 'image/jpeg')

