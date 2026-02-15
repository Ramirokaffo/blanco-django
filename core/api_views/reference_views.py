"""
Vues pour les données de référence (lookup tables).
Correspond aux anciens endpoints Flask:
  - GET /get_category
  - GET /get_rayon
  - GET /get_gamme
  - GET /get_grammage_type
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import Category, Rayon, Gamme, GrammageType
from core.serializers.product_serializers import (
    CategorySerializer, RayonSerializer, GammeSerializer, GrammageTypeSerializer,
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_categories(request):
    """
    Liste de toutes les catégories.
    Ancien Flask: GET /get_category
    """
    categories = Category.objects.filter(delete_at__isnull=True)
    return Response(CategorySerializer(categories, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_rayons(request):
    """
    Liste de tous les rayons.
    Ancien Flask: GET /get_rayon
    """
    rayons = Rayon.objects.filter(delete_at__isnull=True)
    return Response(RayonSerializer(rayons, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_gammes(request):
    """
    Liste de toutes les gammes.
    Ancien Flask: GET /get_gamme
    """
    gammes = Gamme.objects.filter(delete_at__isnull=True)
    return Response(GammeSerializer(gammes, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_grammage_types(request):
    """
    Liste de tous les types de grammage.
    Ancien Flask: GET /get_grammage_type
    """
    grammage_types = GrammageType.objects.filter(delete_at__isnull=True)
    return Response(GrammageTypeSerializer(grammage_types, many=True).data)

