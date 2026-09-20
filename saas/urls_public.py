"""Routes du site public et du parcours d'inscription."""

from django.urls import path

from saas.views import public_views

app_name = "saas"

urlpatterns = [
    path("", public_views.accueil, name="accueil"),
    path("inscription/", public_views.inscription, name="inscription"),
    path("inscription/verifier-slug/", public_views.verifier_slug, name="verifier_slug"),
    path(
        "inscription/<slug:slug>/verification-envoyee/",
        public_views.verification_envoyee, name="verification_envoyee",
    ),
    path(
        "inscription/<slug:slug>/renvoyer/",
        public_views.renvoyer_verification, name="renvoyer_verification",
    ),
    path(
        "inscription/confirmer/<slug:slug>/<str:token>/",
        public_views.confirmer, name="confirmer",
    ),
    path(
        "inscription/<slug:slug>/preparation/",
        public_views.preparation, name="preparation",
    ),
    path("inscription/<slug:slug>/etat/", public_views.etat, name="etat"),
]
