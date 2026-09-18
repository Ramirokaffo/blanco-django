"""
Vues pour la gestion du personnel.
Correspond aux anciens endpoints Flask:
  - GET  /get_user_by_id/<user_id>
  - GET  /get_staff_by_login/<login>
  - POST /create_user
  - POST /update_user

Règles d'accès :
  - la création de compte reste ouverte (écran d'inscription de l'app mobile)
    mais le compte est créé INACTIF : un administrateur doit l'activer avant
    la première connexion. Un superuser authentifié crée des comptes actifs.
  - un utilisateur ne peut modifier que son propre compte (et pas son
    ``username`` ni son ``role``) ; un superuser peut tout modifier.
"""

from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from core.api_permissions import IsSelfOrSuperUser
from core.serializers.staff_serializers import (
    StaffSerializer, StaffCreateSerializer, StaffUpdateSerializer,
)
from core.services.auth_service import AuthService
from core.services.staff_service import StaffService


class SignupRateThrottle(AnonRateThrottle):
    scope = 'signup'


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
@permission_classes([IsAuthenticated])
def get_staff_by_login(request, login):
    """
    Récupérer un utilisateur par son login.
    Ancien Flask: GET /get_staff_by_login/<login>
    (authentification requise : évite l'énumération des comptes.)
    """
    user = StaffService.get_by_username(login)
    if user:
        return Response({'status': 1, 'user': StaffSerializer(user).data})
    return Response({'status': 0})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupRateThrottle])
def create_user(request):
    """
    Créer un utilisateur.
    Ancien Flask: POST /create_user

    Inscription depuis l'app mobile : le compte est créé désactivé
    (``is_active=False``) et sans module. Un superuser authentifié qui appelle
    cet endpoint crée en revanche un compte actif.
    """
    requester = request.user
    created_by_admin = bool(requester and requester.is_authenticated and requester.is_superuser)

    serializer = StaffCreateSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save(is_active=created_by_admin)
        payload = {
            'status': 1,
            'user': StaffSerializer(user).data,
        }
        if not created_by_admin:
            payload['message'] = _(
                "Compte créé. Il doit être activé par un administrateur avant la première connexion."
            )
        return Response(payload, status=status.HTTP_201_CREATED)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated, IsSelfOrSuperUser])
def update_user(request, user_id):
    """
    Mettre à jour un utilisateur.
    Ancien Flask: POST /update_user
    """
    user = StaffService.get_by_id(user_id)
    if not user:
        return Response({'status': 0, 'error': _("Utilisateur introuvable.")},
                        status=status.HTTP_404_NOT_FOUND)

    # Vérification objet : soi-même ou superuser
    permission = IsSelfOrSuperUser()
    if not permission.has_object_permission(request, None, user):
        return Response({'status': 0, 'error': permission.message},
                        status=status.HTTP_403_FORBIDDEN)

    serializer = StaffUpdateSerializer(
        user, data=request.data, partial=True,
        context={'request': request},
    )
    if serializer.is_valid():
        updated_user = serializer.save()
        payload = {
            'status': 1,
            'user': StaffSerializer(updated_user).data,
        }
        # Si l'utilisateur a changé SON mot de passe, son ancien token a été
        # révoqué : on lui renvoie le nouveau pour ne pas le déconnecter.
        if serializer.password_changed and updated_user.pk == request.user.pk:
            payload['token'] = AuthService.get_or_create_token(updated_user)
        return Response(payload)

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)
