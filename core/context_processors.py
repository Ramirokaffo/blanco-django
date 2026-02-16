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


def system_settings_context(request):
    """
    Injecte les paramètres système (nom, logo, etc.) dans le contexte
    de tous les templates.
    """
    from core.models import SystemSettings
    settings = SystemSettings.get_settings()
    return {
        'system_settings': settings,
    }

