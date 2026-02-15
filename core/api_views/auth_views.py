"""
Vues d'authentification.
Correspond à l'ancien endpoint Flask: GET /login/<login>/<password>
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.serializers.auth_serializers import LoginSerializer
from core.serializers.staff_serializers import StaffSerializer
from core.services.auth_service import AuthService


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Authentification d'un utilisateur.
    Ancien Flask: GET /login/<login>/<password>
    Nouveau:      POST /api/auth/login/  { username, password }
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        token = AuthService.get_or_create_token(user)
        return Response({
            'status': 1,
            'token': token,
            'user': StaffSerializer(user).data,
        })

    return Response({
        'status': 0,
        'errors': serializer.errors,
    }, status=status.HTTP_400_BAD_REQUEST)

