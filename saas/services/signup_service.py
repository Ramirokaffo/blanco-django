"""
Parcours d'inscription d'une nouvelle entreprise.

Choix structurant : **l'entreprise est créée dès la soumission du formulaire**,
au statut ``PENDING_VERIFICATION``, et non après la vérification de l'adresse.

Motif : le sous-domaine doit être réservé immédiatement, et l'on refuse d'avoir
deux sources de vérité pour son unicité — une seule contrainte, sur une seule
table. Les inscriptions jamais confirmées sont purgées au bout de quelques
jours, ce qui libère le sous-domaine.

Le mot de passe est haché dès la saisie : le clair ne persiste jamais, pas même
le temps d'un enregistrement.
"""

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from saas.constants import (
    ActionsAudit,
    PURGE_INSCRIPTIONS_JOURS,
    VERIFICATION_DUREE_HEURES,
)
from saas.models import (
    Company,
    CompanyStatus,
    Domain,
    DomainKind,
    Plan,
    SignupRequest,
    empreinte,
    generer_jeton,
)
from saas.services import audit_service, slug_service


class InscriptionInvalide(ValueError):
    """L'inscription ne peut pas aboutir. Message destiné à l'utilisateur."""


@transaction.atomic
def creer_inscription(*, nom, slug, email, mot_de_passe, langue="fr",
                      domaine_plateforme="", gabarit_base="blanco_t_{slug}",
                      contact_nom="", contact_telephone="", request=None):
    """
    Crée l'entreprise (inactive) et l'inscription à vérifier.

    Retourne ``(inscription, jeton_en_clair)``. Le jeton n'est retourné qu'ici :
    seule son empreinte est stockée, et le clair ne vit que dans le lien
    envoyé par e-mail.
    """
    slug = slug_service.valider_disponibilite(slug, domaine_plateforme)

    nom = (nom or "").strip()
    if not nom:
        raise InscriptionInvalide("Le nom de l'entreprise est obligatoire.")

    entreprise = Company.objects.create(
        name=nom,
        slug=slug,
        db_name=slug_service.nom_de_base(slug, gabarit_base),
        status=CompanyStatus.PENDING_VERIFICATION,
        contact_email=email,
        contact_name=contact_nom,
        contact_phone=contact_telephone,
        language=langue,
        plan=Plan.get_default(),
    )

    if domaine_plateforme:
        Domain.objects.create(
            company=entreprise,
            hostname=f"{slug}.{domaine_plateforme}",
            kind=DomainKind.SUBDOMAIN,
            is_primary=True,
            # Vérifié seulement à la mise en service : tant que l'espace
            # n'existe pas, le nom d'hôte ne doit rien servir.
            is_verified=False,
        )

    jeton = generer_jeton()
    inscription = SignupRequest.objects.create(
        company=entreprise,
        email=email,
        password_hash=make_password(mot_de_passe),
        token_hash=empreinte(jeton),
        expires_at=timezone.now() + timezone.timedelta(hours=VERIFICATION_DUREE_HEURES),
        ip=_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
    )

    audit_service.log(
        ActionsAudit.SIGNUP_CREATED, company=entreprise,
        target=email, request=request,
    )
    return inscription, jeton


def _ip(request):
    if request is None:
        return None
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def trouver_inscription(slug, jeton):
    """
    Retrouve une inscription à partir du couple (sous-domaine, jeton).

    Retourne ``None`` dans tous les cas d'échec — jeton inconnu, expiré, déjà
    utilisé — sans jamais les distinguer : la vue affiche un message unique,
    pour ne pas offrir d'oracle.
    """
    inscription = SignupRequest.objects.filter(company__slug=slug).first()
    if inscription is None:
        return None
    if not inscription.correspond_au_jeton(jeton):
        return None
    if inscription.est_expiree:
        return None
    return inscription


@transaction.atomic
def verifier_adresse(inscription, *, request=None):
    """
    Marque l'adresse comme vérifiée et met le provisionnement en file.

    Idempotent : rejouer le lien ne crée pas un second travail.
    """
    from saas.services import provisioning_service

    entreprise = inscription.company

    if not inscription.est_verifiee:
        inscription.verified_at = timezone.now()
        inscription.save(update_fields=["verified_at"])
        audit_service.log(
            ActionsAudit.EMAIL_VERIFIED, company=entreprise,
            target=inscription.email, request=request,
        )

    if entreprise.status == CompanyStatus.PENDING_VERIFICATION:
        entreprise.status = CompanyStatus.PROVISIONING
        entreprise.save(update_fields=["status"])

    if entreprise.status != CompanyStatus.ACTIVE:
        provisioning_service.mettre_en_file(entreprise)
    return entreprise


def purger_inscriptions_abandonnees(maintenant=None):
    """
    Supprime les inscriptions jamais vérifiées et libère leur sous-domaine.

    Retourne le nombre d'entreprises supprimées.
    """
    maintenant = maintenant or timezone.now()
    limite = maintenant - timezone.timedelta(days=PURGE_INSCRIPTIONS_JOURS)

    entreprises = Company.objects.filter(
        status=CompanyStatus.PENDING_VERIFICATION,
        create_at__lt=limite,
    )
    nombre = entreprises.count()
    entreprises.delete()
    return nombre
