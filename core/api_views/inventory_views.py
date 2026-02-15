"""
Vues pour la gestion des inventaires.
Correspond à l'ancien endpoint Flask: POST /create_inventory
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.serializers.inventory_serializers import (
    InventoryCreateSerializer, InventorySerializer,
)
from core.services.inventory_service import InventoryService


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_inventory(request):
    """
    Créer un inventaire pour un produit.
    Ancien Flask: POST /create_inventory
    """
    serializer = InventoryCreateSerializer(data=request.data)
    if serializer.is_valid():
        inventory = InventoryService.create_inventory(
            validated_data=serializer.validated_data,
            staff=request.user,
        )
        return Response({
            'status': 1,
            'inventory': InventorySerializer(inventory).data,
        }, status=status.HTTP_201_CREATED)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)

