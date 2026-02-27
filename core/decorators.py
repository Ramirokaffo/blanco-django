"""
Decorators pour le contrôle d'accès par module.
"""

from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def module_required(module_code):
    """
    Decorator qui vérifie que l'utilisateur connecté a accès au module spécifié.
    
    Usage:
        @login_required
        @module_required('sales')
        def sales_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            # Les superusers ont accès à tout
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if request.user.has_module_access(module_code):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden(
                "<h1>Accès refusé</h1>"
                "<p>Vous n'avez pas accès à ce module. "
                "Contactez votre administrateur.</p>"
                "<a href='/'>Retour au tableau de bord</a>"
            )
        return _wrapped_view
    return decorator

