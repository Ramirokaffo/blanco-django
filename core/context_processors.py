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


def deployment_mode_context(request):
    """
    Expose le mode de déploiement et l'entreprise courante aux gabarits.

    Permet de n'afficher les éléments propres à l'offre hébergée (invitation
    d'employés, par exemple) que lorsqu'ils ont un sens. En installation
    mono-client, ``is_saas`` est faux et ``tenant`` vaut ``None``.
    """
    from blanco.modes import is_saas

    return {
        'is_saas': is_saas(),
        'tenant': getattr(request, 'tenant', None),
    }


def user_modules_context(request):
    """
    Injecte la liste des codes de modules autorisés pour l'utilisateur connecté.
    Disponible dans tous les templates via {{ user_modules }}.
    """
    if hasattr(request, 'user') and request.user.is_authenticated:
        return {
            'user_modules': request.user.get_allowed_module_codes(),
        }
    return {
        'user_modules': [],
    }


def alerts_context(request):
    """
    Injecte les compteurs d'alertes (stock bas, échéances de paiement en
    retard) pour la cloche de notification du header.

    Avant ceci, ces informations n'étaient visibles que sur le tableau de
    bord : un utilisateur qui travaillait sur une autre page (ventes,
    crédits...) ne les voyait pas tant qu'il n'ouvrait pas explicitement le
    dashboard. Chaque compteur est gated par module, comme le reste de la
    navigation, pour ne pas exposer des informations de stock ou de
    trésorerie à un utilisateur qui n'y a pas accès.
    """
    empty = {'alert_low_stock_count': 0, 'alert_overdue_payments_count': 0, 'alert_total_count': 0}
    if not (hasattr(request, 'user') and request.user.is_authenticated):
        return empty

    from datetime import date
    from django.db.models import F
    from core.models import Product, PaymentSchedule

    user = request.user
    low_stock_count = 0
    overdue_count = 0

    if user.is_superuser or user.has_module_access('products'):
        low_stock_count = Product.objects.filter(
            delete_at__isnull=True, stock__lte=F('stock_limit'),
        ).exclude(stock_limit__isnull=True).count()

    if user.is_superuser or user.has_module_access('reports'):
        overdue_count = PaymentSchedule.objects.filter(
            delete_at__isnull=True, due_date__lt=date.today(),
        ).exclude(status='PAID').count()

    return {
        'alert_low_stock_count': low_stock_count,
        'alert_overdue_payments_count': overdue_count,
        'alert_total_count': low_stock_count + overdue_count,
    }

