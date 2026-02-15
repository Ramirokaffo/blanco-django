"""
Context processors pour injecter des données globales dans tous les templates.
"""

from core.services.qrcode_service import QRCodeService


def qrcode_context(request):
    """
    Injecte le QR code du serveur (base64) et l'adresse IP:port
    dans le contexte de tous les templates.
    """
    return {
        'server_qr_base64': QRCodeService.get_qr_base64(),
        'server_address': QRCodeService.get_server_address(),
    }

