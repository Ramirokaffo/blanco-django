"""
Stockage des fichiers déposés, cloisonné par entreprise.

Contrainte de compatibilité
---------------------------
Les lignes déjà en base stockent des noms relatifs comme ``product/photo.jpg``
(``ProductImage.image``) ou ``settings/logo/logo.png``
(``SystemSettings.company_logo``). **Ces valeurs ne doivent pas changer** :
les modifier imposerait une migration de données sur chaque installation
existante, pour un bénéfice nul.

On déplace donc la **racine**, jamais le nom : le stockage pointe sur
``MEDIA_ROOT/tenants/<sous-domaine>/`` lorsqu'une société est active, et sur
``MEDIA_ROOT`` sinon. Conséquences :

* ``upload_to='product/'`` reste inchangé dans les modèles ;
* ``migration_service`` peut continuer d'écrire ``product/<fichier>`` en dur ;
* les gabarits (``{{ image.image.url }}``) produisent toujours
  ``/media/product/…`` — l'URL est déjà discriminée par le nom d'hôte ;
* le mode mono-client ne voit **aucune** différence.

``base_location``, ``location`` et ``base_url`` sont des ``cached_property``
dans ``FileSystemStorage`` : on les redéfinit en ``property`` pour qu'elles
soient réévaluées à chaque accès. L'instance est partagée entre fils
d'exécution (``default_storage`` est un objet de module), mais ces propriétés
sont sans état — elles ne lisent que le contexte du fil courant.
"""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from saas.context import get_current_key

#: Sous-dossier de MEDIA_ROOT regroupant les médias des sociétés.
DOSSIER_SOCIETES = "tenants"


def tenant_media_root() -> str:
    """Racine des médias : celle de la société active, sinon ``MEDIA_ROOT``."""
    cle = get_current_key()
    if not cle:
        return settings.MEDIA_ROOT
    return os.path.join(settings.MEDIA_ROOT, DOSSIER_SOCIETES, cle)


class TenantFileSystemStorage(FileSystemStorage):
    """Stockage de fichiers dont la racine suit la société active."""

    @property
    def base_location(self):
        return tenant_media_root()

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        # Inchangée : le cloisonnement vient de l'hôte, pas du chemin public.
        return settings.MEDIA_URL
