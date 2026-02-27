"""
Configuration personnalisée pour l'administration Django Blanco
"""

from django.contrib import admin


def configure_admin_site():
    """Configure le site d'administration Blanco"""
    admin.site.site_header = "Administration Blanco"
    admin.site.site_title = "Administration Blanco"
    admin.site.index_title = "Panneau d'administration Blanco"


# Appliquer la configuration
configure_admin_site()
