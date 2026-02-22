"""
Vues utilitaires.
Correspond à l'ancien endpoint Flask: GET /test_connexion
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.services.qrcode_service import QRCodeService


@api_view(['GET'])
@permission_classes([AllowAny])
def test_connection(request):
    """
    Test de connexion au serveur.
    Ancien Flask: GET /test_connexion
    """
    return Response({'status': 1})


@api_view(['GET'])
@permission_classes([AllowAny])
def refresh_qr(request):
    """
    Vérifie si l'IP du serveur a changé et régénère le QR code si nécessaire.
    Retourne le QR code actuel (base64), l'adresse serveur et un flag 'changed'.
    """
    result = QRCodeService.refresh_server_qr()
    return Response({
        'qr_base64': result['qr_base64'],
        'server_address': result['server_address'],
        'changed': result['changed'],
    })

