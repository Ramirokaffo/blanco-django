"""
Routes servies sur l'espace d'une entreprise cliente (mode SaaS).

Différence essentielle avec ``blanco.urls`` : **l'administration Django n'y
est pas montée**.

Pourquoi c'est indispensable
----------------------------
Le propriétaire d'un espace est ``is_superuser`` dans sa propre base — c'est le
seul mécanisme existant qui lui donne accès à ses douze modules et à la gestion
de ses employés (``core/decorators.py`` et ``core/api_permissions.py`` font
passer tout superutilisateur). Or le routeur envoie l'application ``saas`` vers
la base plateforme **inconditionnellement** : un propriétaire qui atteindrait
``/admin/saas/company/`` y lirait la liste complète des clients de la
plateforme — raison sociale, contact, et jusqu'au nom de la base de données de
chacun — avec droit d'écriture.

On ne touche donc pas au mécanisme d'autorisation (le durcir partout serait
risqué), on retire la porte : sur un hôte client, ``/admin/`` n'existe pas.
Second verrou indépendant : le propriétaire est créé avec ``is_staff=False``,
ce qui fait échouer ``AdminSite.has_permission`` même si cette URLconf était
contournée. Les deux verrous ne peuvent pas tomber pour la même raison.

Les clients disposent de leurs propres pages « Paramètres » : l'administration
Django ne leur manque pas.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from saas.views import public_views

urlpatterns = [
    # Première entrée dans l'espace, juste après sa création : ticket à usage
    # unique et de courte durée, valable sur ce seul nom d'hôte.
    path(
        "premiere-connexion/<str:token>/",
        public_views.connexion_initiale,
        name="connexion_initiale",
    ),
    # Changement de langue (POST language=fr|en) : cookie LANGUAGE_COOKIE_NAME
    path("i18n/", include("django.conf.urls.i18n")),
    # Catalogue de traductions pour le JavaScript (domaine djangojs)
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("api/", include("core.api_urls", namespace="api")),
    path("", include("core.urls")),
]

# En développement uniquement : les médias sont servis par le serveur de
# développement. En production, ils passent par le reverse proxy ou par une
# vue dédiée qui refuse tout accès hors contexte société.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
