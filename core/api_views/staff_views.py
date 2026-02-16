"""
Vues pour la gestion du personnel.
Correspond aux anciens endpoints Flask:
  - GET  /get_user_by_id/<user_id>
  - GET  /get_staff_by_login/<login>
  - POST /create_user
  - POST /update_user
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from core.serializers.staff_serializers import (
    StaffSerializer, StaffCreateSerializer, StaffUpdateSerializer,
)
from core.services.staff_service import StaffService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_by_id(request, user_id):
    """
    Récupérer un utilisateur par son ID.
    Ancien Flask: GET /get_user_by_id/<user_id>
    """
    user = StaffService.get_by_id(user_id)
    if not user:
        return Response(None, status=status.HTTP_404_NOT_FOUND)
    return Response(StaffSerializer(user).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_staff_by_login(request, login):
    """
    Récupérer un utilisateur par son login.
    Ancien Flask: GET /get_staff_by_login/<login>
    """
    user = StaffService.get_by_username(login)
    if user:
        return Response({'status': 1, 'user': StaffSerializer(user).data})
    return Response({'status': 0})


@api_view(['POST'])
@permission_classes([AllowAny])
def create_user(request):
    """
    Créer un utilisateur.
    Ancien Flask: POST /create_user
    """
    serializer = StaffCreateSerializer(data=request.data, partial=True)
    if serializer.is_valid():
        user = serializer.save()
        return Response({
            'status': 1,
            'user': StaffSerializer(user).data,
        }, status=status.HTTP_201_CREATED)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_user(request, user_id):
    """
    Mettre à jour un utilisateur.
    Ancien Flask: POST /update_user
    """
    user = StaffService.get_by_id(user_id)
    if not user:
        return Response({'status': 0, 'error': 'Utilisateur introuvable.'},
                        status=status.HTTP_404_NOT_FOUND)

    serializer = StaffUpdateSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        updated_user = serializer.save()
        return Response({
            'status': 1,
            'user': StaffSerializer(updated_user).data,
        })

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)

