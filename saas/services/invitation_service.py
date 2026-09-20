"""
Invitations d'employés.

Le point délicat : **le jeton vit dans la base de la plateforme, l'utilisateur
dans celle de la société.**

Il est résolu par l'adressage. Le lien envoyé pointe sur le sous-domaine de
l'entreprise (``https://acme.blanco.app/invitation/<jeton>/``), donc le
middleware a déjà résolu ``request.tenant`` à partir du nom d'hôte **avant**
toute lecture du jeton. La recherche porte alors sur le couple
``(entreprise, empreinte du jeton)`` : un jeton émis pour une société et
présenté sur l'espace d'une autre ne correspond à rien.

Absence d'atomicité entre les deux bases — assumée
--------------------------------------------------
On crée d'abord l'utilisateur dans la base de la société, **puis** on marque
l'invitation acceptée dans celle de la plateforme. Le pire cas est donc bénin :
utilisateur créé, invitation restée « en attente », rattrapée au rejeu du lien.
L'ordre inverse aurait produit le cas irrécupérable — invitation consommée,
aucun compte créé.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from saas.constants import ActionsAudit, INVITATION_DUREE_JOURS
from saas.context import platform_context, tenant_context
from saas.models import Invitation, InvitationStatus, empreinte, generer_jeton
from saas.services import audit_service


class InvitationInvalide(ValueError):
    """L'invitation ne peut pas être créée ou acceptée."""


def codes_de_modules_valides(codes):
    """Filtre les codes reçus sur la liste des modules connus."""
    from core.models.settings_models import DEFAULT_MODULES

    connus = {code for code, *_reste in DEFAULT_MODULES}
    return [code for code in (codes or []) if code in connus]


def quota_atteint(company) -> bool:
    """
    Vrai si l'offre de l'entreprise n'autorise pas d'utilisateur de plus.

    Le décompte se fait dans la base de la société, la limite dans celle de la
    plateforme : d'où le passage explicite d'un contexte à l'autre.
    """
    offre = company.plan
    if offre is None or offre.max_users is None:
        return False

    from django.contrib.auth import get_user_model

    with tenant_context(company):
        actifs = get_user_model().objects.filter(
            is_active=True, delete_at__isnull=True
        ).count()
    return actifs >= offre.max_users


@transaction.atomic
def creer_invitation(company, *, email, module_codes, invite_par=None,
                     firstname="", lastname="", role=""):
    """
    Crée une invitation et retourne ``(invitation, jeton_en_clair)``.

    Le jeton n'est retourné qu'ici : seule son empreinte est stockée.
    """
    email = (email or "").strip().lower()
    if not email:
        raise InvitationInvalide(_("Indiquez une adresse e-mail."))

    from django.contrib.auth import get_user_model

    with tenant_context(company):
        deja_membre = get_user_model().objects.filter(
            email__iexact=email, delete_at__isnull=True, is_active=True
        ).exists()
    if deja_membre:
        raise InvitationInvalide(_("Cette personne fait déjà partie de votre équipe."))

    en_cours = Invitation.objects.filter(
        company=company, email=email, status=InvitationStatus.PENDING
    ).first()
    if en_cours is not None and not en_cours.est_expiree:
        raise InvitationInvalide(_("Une invitation est déjà en cours pour cette adresse."))
    if en_cours is not None:
        en_cours.status = InvitationStatus.EXPIRED
        en_cours.save(update_fields=["status"])

    if quota_atteint(company):
        raise InvitationInvalide(_(
            "Votre offre ne permet pas d'ajouter un utilisateur de plus."
        ))

    jeton = generer_jeton()
    invitation = Invitation.objects.create(
        company=company,
        email=email,
        firstname=firstname,
        lastname=lastname,
        role=role,
        module_codes=codes_de_modules_valides(module_codes),
        token_hash=empreinte(jeton),
        expires_at=timezone.now() + timezone.timedelta(days=INVITATION_DUREE_JOURS),
        invited_by_user_id=getattr(invite_par, "pk", None),
        invited_by_label=(
            f"{invite_par.get_full_name()} (@{invite_par.username})"[:150]
            if invite_par is not None else ""
        ),
    )
    audit_service.log(
        ActionsAudit.INVITATION_SENT, company=company, target=email,
        metadata={"modules": invitation.module_codes},
    )
    return invitation, jeton


def renouveler_jeton(invitation):
    """Régénère le jeton d'une invitation (renvoi du message)."""
    jeton = generer_jeton()
    invitation.token_hash = empreinte(jeton)
    invitation.expires_at = timezone.now() + timezone.timedelta(days=INVITATION_DUREE_JOURS)
    invitation.send_count += 1
    invitation.last_sent_at = timezone.now()
    invitation.save(update_fields=[
        "token_hash", "expires_at", "send_count", "last_sent_at",
    ])
    return jeton


def trouver_invitation(company, jeton):
    """
    Retrouve une invitation utilisable pour cette entreprise.

    Retourne ``None`` dans tous les cas d'échec, sans les distinguer : la vue
    affiche un message unique pour ne pas offrir d'oracle.
    """
    if company is None or not jeton:
        return None

    for invitation in Invitation.objects.filter(
        company=company, status=InvitationStatus.PENDING
    ):
        if invitation.correspond_au_jeton(jeton) and not invitation.est_expiree:
            return invitation
    return None


def revoquer(invitation, *, par=None):
    invitation.status = InvitationStatus.REVOKED
    invitation.save(update_fields=["status"])
    audit_service.log(
        ActionsAudit.INVITATION_REVOKED, company=invitation.company,
        target=invitation.email, actor=par,
    )


def accepter(invitation, *, username, mot_de_passe, firstname="", lastname=""):
    """
    Crée le compte de l'employé puis marque l'invitation acceptée.

    L'ordre est délibéré : voir l'en-tête du module.
    """
    from django.contrib.auth import get_user_model
    from core.models.settings_models import AppModule

    company = invitation.company
    User = get_user_model()

    with tenant_context(company):
        if User.objects.filter(username=username).exists():
            raise InvitationInvalide(_("Cet identifiant est déjà pris."))

        with transaction.atomic(using=company.db_alias):
            utilisateur = User(
                username=username,
                email=invitation.email,
                firstname=firstname or invitation.firstname,
                lastname=lastname or invitation.lastname,
                role=invitation.role,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            utilisateur.set_password(mot_de_passe)
            utilisateur.save()

            modules = AppModule.objects.filter(
                code__in=invitation.module_codes, is_active=True
            )
            utilisateur.allowed_modules.set(modules)

    # Le plan de contrôle vit dans une autre base : on en sort explicitement.
    with platform_context():
        # `filter(...).update(...)` et non `save()` : protège du double-clic,
        # deux acceptations simultanées ne peuvent pas passer toutes les deux.
        mises_a_jour = Invitation.objects.filter(
            pk=invitation.pk, status=InvitationStatus.PENDING
        ).update(
            status=InvitationStatus.ACCEPTED,
            accepted_at=timezone.now(),
            accepted_user_id=utilisateur.pk,
        )
        if mises_a_jour:
            audit_service.log(
                ActionsAudit.INVITATION_ACCEPTED, company=company,
                target=invitation.email,
            )
    return utilisateur
