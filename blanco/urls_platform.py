"""
Routes servies sur le domaine de la plateforme (mode SaaS).

C'est le domaine racine (``blanco.app``, ``www.``) et le back-office
(``admin.``). On y trouve le site public et l'inscription ; on n'y trouve
**aucune** page métier de ``core``, qui n'aurait pas de société à interroger.

L'administration Django est montée ici, et ici seulement : sur un espace
client, ``blanco.urls_tenant`` ne la contient pas.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("saas.urls_public")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
