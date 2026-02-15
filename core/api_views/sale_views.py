"""
Vues pour la gestion des ventes.
Correspond à l'ancien endpoint Flask: POST /sale
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.serializers.sale_serializers import SaleCreateSerializer, SaleSerializer
from core.services.sale_service import SaleService


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_sale(request):
    """
    Créer une vente.
    Ancien Flask: POST /sale
    """
    serializer = SaleCreateSerializer(data=request.data)
    if serializer.is_valid():
        try:
            sale = SaleService.create_sale(
                validated_data=serializer.validated_data,
                staff=request.user,
            )
            sale_data = SaleSerializer(sale).data
            return Response({
                'status': 1,
                'message': 'Vente créée avec succès',
                'sale': sale_data,
            }, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({
                'status': 0,
                'error': str(e),
            }, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_sales(request):
    """
    Rechercher des ventes du Daily en cours.
    Paramètre: ?q=<terme>
    """
    query = request.GET.get('q', '').strip()
    sales = SaleService.search_sales(query=query)
    serializer = SaleSerializer(sales, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sale_details(request, sale_id):
    """
    Détails d'une vente par ID.
    """
    sale = SaleService.get_by_id(sale_id)
    if not sale:
        return Response({'error': 'Vente introuvable'},
                        status=status.HTTP_404_NOT_FOUND)
    serializer = SaleSerializer(sale)
    return Response(serializer.data)

