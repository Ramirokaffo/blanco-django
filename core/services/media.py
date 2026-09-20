"""
Racine des fichiers déposés, selon le mode de déploiement.

``core`` ne doit JAMAIS importer l'application ``saas`` au niveau module :
cette dernière n'existe pas en installation mono-client. L'import est donc fait
dans le corps de la fonction, derrière un contrôle de mode.

En mono-client, la valeur retournée est exactement ``settings.MEDIA_ROOT`` :
le comportement historique est préservé au chemin près.
"""

import os

from django.conf import settings


def current_media_root() -> str:
    """
    Racine effective des médias pour le contexte courant.

    En mode SaaS et lorsqu'une société est active, retourne
    ``MEDIA_ROOT/tenants/<sous-domaine>/`` ; sinon ``MEDIA_ROOT``.
    """
    if getattr(settings, "IS_SAAS", False):
        from saas.storage import tenant_media_root

        return tenant_media_root()
    return settings.MEDIA_ROOT


def media_path(*parties) -> str:
    """Chemin absolu sous la racine des médias du contexte courant."""
    return os.path.join(current_media_root(), *parties)
