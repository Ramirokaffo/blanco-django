"""
Vues utilitaires.
Correspond à l'ancien endpoint Flask: GET /test_connexion
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def test_connection(request):
    """
    Test de connexion au serveur.
    Ancien Flask: GET /test_connexion
    """
    return Response({'status': 1})

