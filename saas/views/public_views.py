"""
Site public et parcours d'inscription.

Servi sur le domaine racine de la plateforme uniquement (voir
``blanco/urls_platform.py``).
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login as auth_login
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from saas.constants import VERIFICATION_DUREE_HEURES
from saas.context import tenant_context
from saas.forms import SignupForm
from saas.models import Company, CompanyStatus, ProvisionStep, SignupRequest
from saas.services import signup_service, slug_service
from saas.services.mail_service import queue_mail

logger = logging.getLogger(__name__)

#: Fréquence maximale de la vérification de disponibilité, par adresse IP.
#: C'est un oracle d'énumération : sans limite, on offrirait la liste des
#: clients de la plateforme à qui sait boucler.
SLUG_MAX_APPELS = 20
SLUG_FENETRE_SECONDES = 60

#: Nombre maximal de renvois du courriel de vérification.
RENVOI_MAX = 3
RENVOI_DELAI_SECONDES = 120


def _ip(request):
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "inconnue"


def _domaine_plateforme():
    return getattr(settings, "BLANCO_PLATFORM_DOMAIN", "")


def _lien_absolu(request, chemin):
    schema = "https" if request.is_secure() else "http"
    return f"{schema}://{request.get_host()}{chemin}"


def _envoyer_verification(request, inscription, jeton):
    chemin = reverse("saas:confirmer", args=[inscription.company.slug, jeton])
    queue_mail(
        "verification",
        inscription.email,
        {
            "entreprise": inscription.company.name,
            "lien": _lien_absolu(request, chemin),
            "heures": VERIFICATION_DUREE_HEURES,
        },
        company=inscription.company,
        language=inscription.company.language,
        priority=20,
    )
    inscription.send_count += 1
    inscription.last_sent_at = timezone.now()
    inscription.save(update_fields=["send_count", "last_sent_at"])


# ──────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────

def accueil(request):
    """Page de présentation de l'offre."""
    return render(request, "saas/accueil.html")


@require_http_methods(["GET", "POST"])
def inscription(request):
    """Formulaire de création d'un espace."""
    if request.method == "POST":
        formulaire = SignupForm(request.POST)
        if formulaire.is_valid():
            donnees = formulaire.cleaned_data
            demande, jeton = signup_service.creer_inscription(
                nom=donnees["nom"],
                slug=donnees["slug"],
                email=donnees["email"],
                mot_de_passe=donnees["mot_de_passe"],
                langue=donnees["langue"],
                domaine_plateforme=_domaine_plateforme(),
                gabarit_base=getattr(
                    settings, "TENANT_DB_NAME_TEMPLATE", "blanco_t_{slug}"
                ),
                contact_nom=donnees["contact_nom"],
                contact_telephone=donnees["contact_telephone"],
                request=request,
            )
            _envoyer_verification(request, demande, jeton)
            return redirect("saas:verification_envoyee", slug=demande.company.slug)
    else:
        formulaire = SignupForm()

    return render(request, "saas/inscription.html", {
        "formulaire": formulaire,
        "domaine_plateforme": _domaine_plateforme(),
    })


def verification_envoyee(request, slug):
    """Écran « consultez votre boîte e-mail »."""
    entreprise = Company.objects.filter(slug=slug).first()
    if entreprise is None:
        return render(request, "saas/lien_invalide.html", status=404)
    return render(request, "saas/verification_envoyee.html", {
        "entreprise": entreprise,
        "email": entreprise.contact_email,
    })


@require_POST
def renvoyer_verification(request, slug):
    """Renvoie le courriel de vérification, dans une limite raisonnable."""
    inscription_demande = SignupRequest.objects.filter(company__slug=slug).first()

    # On répond toujours la même chose, quel que soit le cas : ne pas révéler
    # si ce sous-domaine correspond à une inscription en cours.
    if (
        inscription_demande is not None
        and not inscription_demande.est_verifiee
        and inscription_demande.send_count < RENVOI_MAX
        and (
            inscription_demande.last_sent_at is None
            or (timezone.now() - inscription_demande.last_sent_at).total_seconds()
            > RENVOI_DELAI_SECONDES
        )
    ):
        from saas.models import empreinte, generer_jeton

        jeton = generer_jeton()
        inscription_demande.token_hash = empreinte(jeton)
        inscription_demande.expires_at = timezone.now() + timezone.timedelta(
            hours=VERIFICATION_DUREE_HEURES
        )
        inscription_demande.save(update_fields=["token_hash", "expires_at"])
        _envoyer_verification(request, inscription_demande, jeton)

    return redirect("saas:verification_envoyee", slug=slug)


def verifier_slug(request):
    """
    Disponibilité d'un sous-domaine, pour le contrôle en direct du formulaire.

    Limité en fréquence par adresse IP : c'est un oracle d'énumération. Le
    message ne distingue jamais « réservé » de « déjà pris ».
    """
    cle = f"_slug-check:{_ip(request)}"
    appels = cache.get(cle, 0)
    if appels >= SLUG_MAX_APPELS:
        return JsonResponse(
            {"disponible": False, "message": _("Trop de vérifications. Patientez un instant.")},
            status=429,
        )
    try:
        cache.incr(cle)
    except ValueError:
        cache.set(cle, 1, SLUG_FENETRE_SECONDES)

    try:
        slug_service.valider_disponibilite(
            request.GET.get("slug", ""), _domaine_plateforme()
        )
    except slug_service.SlugInvalide as exc:
        return JsonResponse({"disponible": False, "message": str(exc)})

    return JsonResponse({"disponible": True, "message": _("Ce sous-domaine est disponible.")})


def confirmer(request, slug, token):
    """Confirme l'adresse et lance la création de l'espace."""
    demande = signup_service.trouver_inscription(slug, token)
    if demande is None:
        # Jeton inconnu, expiré ou déjà consommé : un seul et même message.
        return render(request, "saas/lien_invalide.html", status=404)

    signup_service.verifier_adresse(demande, request=request)
    return redirect("saas:preparation", slug=slug)


def preparation(request, slug):
    """Page d'attente pendant la création de l'espace."""
    entreprise = Company.objects.filter(slug=slug).first()
    if entreprise is None:
        return render(request, "saas/lien_invalide.html", status=404)
    return render(request, "saas/preparation.html", {"entreprise": entreprise})


#: Progression affichée, par étape franchie.
PROGRESSION = {
    "": (5, _("Mise en file d'attente…")),
    ProvisionStep.CREATE_DB: (20, _("Création de votre espace…")),
    ProvisionStep.MIGRATE: (50, _("Installation des tables…")),
    ProvisionStep.SEED: (70, _("Mise en place du plan comptable OHADA…")),
    ProvisionStep.OWNER: (85, _("Création de votre compte…")),
    ProvisionStep.DOMAIN: (95, _("Mise en service de votre adresse…")),
    ProvisionStep.DONE: (100, _("C'est prêt !")),
}


def etat(request, slug):
    """État d'avancement de la création, sondé par la page d'attente."""
    entreprise = Company.objects.filter(slug=slug).first()
    if entreprise is None:
        return JsonResponse({"status": "INTROUVABLE"}, status=404)

    job = entreprise.jobs.filter(kind="PROVISION").order_by("-create_at").first()
    etape = job.step if job else ""
    progression, libelle = PROGRESSION.get(etape, PROGRESSION[""])

    donnees = {
        "status": entreprise.status,
        "step": etape,
        "progress": progression,
        "label": str(libelle),
    }

    if entreprise.status == CompanyStatus.ACTIVE:
        donnees["progress"] = 100
        donnees["label"] = str(PROGRESSION[ProvisionStep.DONE][1])
        donnees["redirect_url"] = _url_de_connexion(entreprise)
    elif entreprise.status == CompanyStatus.PROVISION_FAILED:
        donnees["label"] = str(_(
            "Nous n'avons pas pu créer votre espace. Notre équipe est prévenue."
        ))

    return JsonResponse(donnees)


def _url_de_connexion(entreprise):
    """
    URL d'entrée dans l'espace, avec ticket de connexion si l'on en a un.

    Le ticket évite au propriétaire de ressaisir son mot de passe juste après
    l'inscription. S'il a expiré ou déjà servi, on renvoie simplement vers
    l'espace : l'e-mail de bienvenue contient tout ce qu'il faut.
    """
    from saas.services.provisioning_service import emettre_ticket_connexion

    domaine = entreprise.primary_domain
    if domaine is None:
        return ""

    base = f"https://{domaine.hostname}"
    demande = getattr(entreprise, "signup", None)
    if demande is not None and demande.login_ticket_used_at is None:
        ticket = emettre_ticket_connexion(entreprise)
        if ticket:
            return f"{base}/premiere-connexion/{ticket}/"
    return f"{base}/"


def connexion_initiale(request, token):
    """
    Connecte le propriétaire juste après la création de son espace.

    Le ticket est à usage unique et de courte durée. Il n'est valable que sur
    l'espace auquel il appartient : ``request.tenant`` est déjà résolu par le
    middleware à partir du nom d'hôte, et l'inscription est retrouvée à partir
    de cette entreprise — le couple (hôte, ticket) fait foi.
    """
    # Cette vue est servie sur l'espace du client, pas sur le site public :
    # en cas d'échec on renvoie vers la page de connexion de cet espace, et
    # non vers un gabarit de la plateforme qui n'y est pas routé. Le lien de
    # bienvenue envoyé par e-mail reste utilisable.
    entreprise = getattr(request, "tenant", None)
    if entreprise is None:
        return redirect(settings.LOGIN_URL)

    demande = SignupRequest.objects.filter(company=entreprise).first()
    if demande is None or not demande.ticket_valide(token):
        return redirect(settings.LOGIN_URL)

    User = get_user_model()
    with tenant_context(entreprise):
        proprietaire = User.objects.filter(pk=entreprise.owner_user_id).first()
        if proprietaire is None:
            return redirect(settings.LOGIN_URL)
        auth_login(request, proprietaire, backend="core.auth_backends.ActiveStaffBackend")

    demande.login_ticket_used_at = timezone.now()
    demande.save(update_fields=["login_ticket_used_at"])
    return redirect("/")
