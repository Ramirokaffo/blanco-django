"""
Invitation d'employés, côté espace client.

Ces vues vivent dans ``core`` et non dans ``saas`` : elles créent un
``CustomUser`` dans la base de la société avec ses modules, elles s'affichent
dans la page « Utilisateurs » existante et elles réutilisent le décorateur
``module_required``. Les placer dans ``saas`` aurait imposé de manipuler un
contexte de société partout et de dupliquer la navigation.

Règle d'architecture respectée : ``core`` n'importe **jamais** ``saas`` au
niveau module. Les imports sont dans le corps des fonctions, derrière un
contrôle de mode. En installation mono-client, ces routes renvoient 404 et le
bouton « Inviter » n'apparaît pas.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from blanco.modes import is_saas
from core.decorators import module_required

#: Nombre maximal d'envois pour une même invitation.
RENVOI_MAX = 5


def saas_uniquement(vue):
    """
    Réserve une vue au mode plateforme.

    On renvoie 404 et non 403 : en installation mono-client, ces adresses ne
    doivent pas même laisser deviner qu'une fonctionnalité existe ailleurs.
    """
    @wraps(vue)
    def _enveloppe(request, *args, **kwargs):
        if not is_saas():
            raise Http404()
        return vue(request, *args, **kwargs)

    return _enveloppe


def _entreprise(request):
    entreprise = getattr(request, "tenant", None)
    if entreprise is None:
        raise Http404()
    return entreprise


def _envoyer_invitation(request, invitation, jeton):
    """Met en file l'e-mail d'invitation, dans la langue de l'entreprise."""
    from saas.constants import INVITATION_DUREE_JOURS
    from saas.services.mail_service import queue_mail

    entreprise = invitation.company
    schema = "https" if request.is_secure() else "http"
    lien = f"{schema}://{request.get_host()}/invitation/{jeton}/"

    queue_mail(
        "invitation",
        invitation.email,
        {
            "entreprise": entreprise.name,
            "invitant": invitation.invited_by_label or entreprise.name,
            "lien": lien,
            "jours": INVITATION_DUREE_JOURS,
        },
        company=entreprise,
        language=entreprise.language,
        priority=15,
    )


# ──────────────────────────────────────────────────────────────────────
# Gestion des invitations (responsable de l'espace)
# ──────────────────────────────────────────────────────────────────────

@login_required
@module_required("contacts")
@saas_uniquement
def invitations(request):
    """Liste des invitations en cours et formulaire d'envoi."""
    from core.models.settings_models import AppModule
    from saas.models import Invitation

    entreprise = _entreprise(request)
    return render(request, "core/invitations.html", {
        "invitations": Invitation.objects.filter(
            company=entreprise, delete_at__isnull=True
        ).order_by("-create_at"),
        "modules_disponibles": AppModule.objects.filter(is_active=True).order_by("order"),
        "renvoi_max": RENVOI_MAX,
    })


@login_required
@module_required("contacts")
@saas_uniquement
@require_POST
def envoyer_invitation(request):
    """Crée une invitation et met son e-mail en file."""
    from saas.services import invitation_service

    entreprise = _entreprise(request)
    try:
        invitation, jeton = invitation_service.creer_invitation(
            entreprise,
            email=request.POST.get("email", ""),
            module_codes=request.POST.getlist("modules"),
            invite_par=request.user,
            firstname=request.POST.get("firstname", "").strip(),
            lastname=request.POST.get("lastname", "").strip(),
            role=request.POST.get("role", "").strip(),
        )
    except invitation_service.InvitationInvalide as exc:
        messages.error(request, str(exc))
        return redirect("invitations")

    invitation.send_count = 1
    from django.utils import timezone

    invitation.last_sent_at = timezone.now()
    invitation.save(update_fields=["send_count", "last_sent_at"])

    _envoyer_invitation(request, invitation, jeton)
    messages.success(request, _("Invitation envoyée à %(email)s.") % {"email": invitation.email})
    return redirect("invitations")


@login_required
@module_required("contacts")
@saas_uniquement
@require_POST
def renvoyer_invitation(request, pk):
    """Régénère le jeton et renvoie le message."""
    from saas.models import Invitation, InvitationStatus
    from saas.services import invitation_service

    entreprise = _entreprise(request)
    invitation = Invitation.objects.filter(
        pk=pk, company=entreprise, status=InvitationStatus.PENDING
    ).first()
    if invitation is None:
        raise Http404()

    if invitation.send_count >= RENVOI_MAX:
        messages.error(request, _(
            "Cette invitation a déjà été envoyée plusieurs fois. "
            "Révoquez-la et créez-en une nouvelle."
        ))
        return redirect("invitations")

    jeton = invitation_service.renouveler_jeton(invitation)
    _envoyer_invitation(request, invitation, jeton)
    messages.success(request, _("Invitation renvoyée à %(email)s.") % {"email": invitation.email})
    return redirect("invitations")


@login_required
@module_required("contacts")
@saas_uniquement
@require_POST
def revoquer_invitation(request, pk):
    """Annule une invitation en cours."""
    from saas.models import Invitation, InvitationStatus
    from saas.services import invitation_service

    entreprise = _entreprise(request)
    invitation = Invitation.objects.filter(
        pk=pk, company=entreprise, status=InvitationStatus.PENDING
    ).first()
    if invitation is None:
        raise Http404()

    invitation_service.revoquer(invitation, par=request.user)
    messages.success(request, _("Invitation révoquée."))
    return redirect("invitations")


# ──────────────────────────────────────────────────────────────────────
# Acceptation (employé invité, non connecté)
# ──────────────────────────────────────────────────────────────────────

@saas_uniquement
def accepter_invitation(request, token):
    """
    Création du compte par l'employé invité.

    L'entreprise vient du nom d'hôte, résolu par le middleware avant toute
    lecture du jeton : le couple (hôte, jeton) fait foi. Un jeton émis pour une
    société et présenté ailleurs ne correspond à rien.
    """
    from saas.services import invitation_service

    entreprise = _entreprise(request)
    invitation = invitation_service.trouver_invitation(entreprise, token)
    if invitation is None:
        # Jeton inconnu, expiré ou révoqué : un seul et même message.
        return render(request, "core/invitation_invalide.html", status=404)

    identifiant_propose = invitation.email.split("@")[0]
    erreurs = {}

    if request.method == "POST":
        identifiant = (request.POST.get("username") or "").strip()
        mot_de_passe = request.POST.get("password") or ""
        confirmation = request.POST.get("password_confirmation") or ""

        if not identifiant:
            erreurs["username"] = _("Choisissez un identifiant.")
        if mot_de_passe != confirmation:
            erreurs["password_confirmation"] = _("Les deux mots de passe ne correspondent pas.")
        if mot_de_passe:
            try:
                validate_password(mot_de_passe)
            except ValidationError as exc:
                erreurs["password"] = " ".join(exc.messages)
        else:
            erreurs["password"] = _("Choisissez un mot de passe.")

        if not erreurs:
            try:
                utilisateur = invitation_service.accepter(
                    invitation,
                    username=identifiant,
                    mot_de_passe=mot_de_passe,
                    firstname=(request.POST.get("firstname") or "").strip(),
                    lastname=(request.POST.get("lastname") or "").strip(),
                )
            except invitation_service.InvitationInvalide as exc:
                erreurs["username"] = str(exc)
            else:
                auth_login(
                    request, utilisateur,
                    backend="core.auth_backends.ActiveStaffBackend",
                )
                messages.success(request, _("Bienvenue ! Votre compte est prêt."))
                return redirect("dashboard")

        identifiant_propose = identifiant

    return render(request, "core/invitation_acceptation.html", {
        "invitation": invitation,
        "entreprise": entreprise,
        "identifiant_propose": identifiant_propose,
        "erreurs": erreurs,
    })
