"""
Création de l'espace d'une entreprise.

Six étapes, **toutes idempotentes**, avec point de reprise :

1. ``CREATE_DB``  création de la base et des droits ;
2. ``MIGRATE``    installation du schéma ;
3. ``SEED``       modules, plan comptable OHADA, paramètres système ;
4. ``OWNER``      compte du propriétaire ;
5. ``DOMAIN``     mise en service du sous-domaine ;
6. ``DONE``       activation et ticket de connexion.

Reprise sur échec : une base à moitié migrée n'est **jamais détruite**, on la
termine. La destruction n'a lieu que si l'échec survient pendant la création
même de la base, et uniquement si cette exécution l'avait créée — jamais sur
une base préexistante.

Interdiction formelle du clonage
--------------------------------
Une base société se crée **toujours** vide puis se migre. Jamais par
``CREATE DATABASE ... LIKE``, jamais par restauration d'un gabarit peuplé.
Deux bases clonées partageraient la même ligne ``staff`` — même identifiant,
même empreinte de mot de passe — et une session ou un jeton de l'une serait
alors valide sur l'autre. C'est la seule brèche que l'isolation par base ne
couvre pas d'elle-même.
"""

import logging
import secrets

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

from saas.constants import ActionsAudit, TICKET_CONNEXION_DUREE_MINUTES
from saas.context import tenant_context
from saas.db import ensure_alias, valider_nom_de_base
from saas.models import (
    CompanyStatus,
    JobKind,
    ProvisionStep,
    ProvisioningJob,
    empreinte,
    generer_jeton,
)
from saas.services import audit_service

logger = logging.getLogger(__name__)


class EchecProvisionnement(RuntimeError):
    """Le provisionnement n'a pas pu aboutir."""


# ──────────────────────────────────────────────────────────────────────
# Base de données
# ──────────────────────────────────────────────────────────────────────

#: Alias de la connexion d'administration des bases.
ALIAS_PROVISION = "provision"


def _connexion_administration():
    """
    Connexion disposant du droit de créer des bases.

    Le compte applicatif ne possède pas ``CREATE DATABASE`` : on ouvre une
    connexion dédiée avec ``MYSQL_PROVISION_USER``, dont les identifiants ne
    sont **pas** fournis au conteneur web. Une faille du serveur web ne permet
    donc ni de créer ni de détruire des bases.

    Sans compte dédié configuré — développement, tests, SQLite — on retombe sur
    la connexion par défaut : créer un alias supplémentaire n'apporterait rien
    et perturberait le lanceur de tests de Django, qui instrumente les
    connexions déclarées au début de chaque classe de test.
    """
    utilisateur = getattr(settings, "MYSQL_PROVISION_USER", "")
    if not utilisateur or connections["default"].vendor != "mysql":
        return connections["default"]

    if ALIAS_PROVISION not in connections.settings:
        base = connections.settings["default"]
        configuration = {
            **base,
            "USER": utilisateur,
            "PASSWORD": getattr(settings, "MYSQL_PROVISION_PASSWORD", ""),
        }
        nouvelle = {**connections.settings, ALIAS_PROVISION: configuration}
        connections.__dict__["settings"] = nouvelle
        connections._settings = nouvelle
        settings.DATABASES = nouvelle
    return connections[ALIAS_PROVISION]


def creer_base(db_name: str) -> bool:
    """
    Crée la base si elle n'existe pas. Retourne ``True`` si elle a été créée ici.

    Le nom est validé par expression régulière **avant** interpolation : le DDL
    ne se paramètre pas (``CREATE DATABASE %s`` est impossible), c'est donc la
    seule protection contre une injection.
    """
    valider_nom_de_base(db_name)
    connexion = _connexion_administration()

    if connexion.vendor == "sqlite":
        # En développement/tests sous SQLite, la « base » est un fichier créé
        # à la première connexion : rien à faire ici.
        return False

    with connexion.cursor() as curseur:
        curseur.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            [db_name],
        )
        if curseur.fetchone():
            return False
        curseur.execute(
            f"CREATE DATABASE `{db_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        utilisateur = connections.settings["default"].get("USER")
        if utilisateur:
            curseur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO %s@'%%'", [utilisateur])
            curseur.execute("FLUSH PRIVILEGES")
    return True


def supprimer_base(db_name: str) -> None:
    """Détruit une base. Réservé au nettoyage d'un échec de création."""
    valider_nom_de_base(db_name)
    connexion = _connexion_administration()
    if connexion.vendor == "sqlite":
        return
    with connexion.cursor() as curseur:
        curseur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")


# ──────────────────────────────────────────────────────────────────────
# Étapes
# ──────────────────────────────────────────────────────────────────────

def _etape_migrate(company):
    alias = ensure_alias(company.db_alias, company.db_name)
    # Le signal post_migrate corrigé sème modules et plan comptable DANS cette
    # base : c'est lui qui rend l'étape SEED presque vide.
    call_command("migrate", database=alias, interactive=False, verbosity=0)
    return alias


def _etape_seed(company, alias):
    """Complète le seed : paramètres système de l'entreprise."""
    from core.models import SystemSettings

    with tenant_context(company):
        # `get_or_create(pk=1)` et jamais `create()` : SystemSettings force
        # `self.pk = 1` dans son `save()`.
        parametres, _cree = SystemSettings.objects.get_or_create(pk=1)
        modifie = False
        if parametres.company_name in ("", "BLANCO"):
            parametres.company_name = company.name
            modifie = True
        if not parametres.company_email:
            parametres.company_email = company.contact_email
            modifie = True
        if modifie:
            parametres.save()
    return parametres


def _etape_owner(company, alias, mot_de_passe_hache=None):
    """
    Crée le compte du propriétaire dans la base de l'entreprise.

    Il est ``is_superuser=True`` — seul mécanisme existant lui donnant accès à
    ses douze modules et à la gestion de ses employés — mais
    ``is_staff=False`` : l'administration Django lui reste fermée, second
    verrou indépendant de l'URLconf qui ne la monte pas sur un hôte client.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    identifiant = company.owner_username or company.contact_email.split("@")[0]

    with tenant_context(company):
        proprietaire = User.objects.filter(username=identifiant).first()
        if proprietaire is None:
            proprietaire = User(
                username=identifiant,
                email=company.contact_email,
                is_superuser=True,
                is_staff=False,
                is_active=True,
            )
            if mot_de_passe_hache:
                # L'empreinte a été calculée à l'inscription : le mot de passe
                # en clair n'a jamais été conservé.
                proprietaire.password = mot_de_passe_hache
            else:
                proprietaire.set_unusable_password()
            proprietaire.save()

    company.owner_user_id = proprietaire.pk
    company.owner_username = proprietaire.username
    company.save(update_fields=["owner_user_id", "owner_username"])
    return proprietaire


def _etape_domain(company):
    principal = company.primary_domain
    if principal and not principal.is_verified:
        principal.is_verified = True
        principal.verified_at = timezone.now()
        principal.save(update_fields=["is_verified", "verified_at"])
    return principal


def _etape_done(company):
    from saas.middleware import oublier_hote

    company.status = CompanyStatus.ACTIVE
    company.provisioned_at = company.provisioned_at or timezone.now()
    company.save(update_fields=["status", "provisioned_at"])

    # Sans cette invalidation, l'espace resterait injoignable jusqu'à cinq
    # minutes : le middleware a mis en cache « hôte inconnu ».
    for domaine in company.domains.all():
        oublier_hote(domaine.hostname)


def emettre_ticket_connexion(company):
    """
    Ticket à usage unique connectant le propriétaire sans mot de passe.

    Très court (quelques minutes) et consommé au premier usage : il sert
    uniquement à enchaîner sans friction depuis la page d'attente. Un e-mail
    de bienvenue part en parallèle, de sorte que rien n'est perdu si l'onglet
    est fermé.
    """
    inscription = getattr(company, "signup", None)
    if inscription is None:
        return None

    ticket = generer_jeton()
    inscription.login_ticket_hash = empreinte(ticket)
    inscription.login_ticket_expires_at = timezone.now() + timezone.timedelta(
        minutes=TICKET_CONNEXION_DUREE_MINUTES
    )
    inscription.login_ticket_used_at = None
    inscription.save(update_fields=[
        "login_ticket_hash", "login_ticket_expires_at", "login_ticket_used_at",
    ])
    return ticket


# ──────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────

ORDRE_ETAPES = [
    ProvisionStep.CREATE_DB,
    ProvisionStep.MIGRATE,
    ProvisionStep.SEED,
    ProvisionStep.OWNER,
    ProvisionStep.DOMAIN,
    ProvisionStep.DONE,
]


def provision(company, *, job=None, mot_de_passe_hache=None):
    """
    Crée l'espace d'une entreprise. Idempotent et reprenable.

    ``job`` sert à mémoriser l'étape atteinte pour une éventuelle reprise.
    """
    def marquer(etape):
        if job is not None:
            job.step = etape
            job.save(update_fields=["step"])

    if company.status == CompanyStatus.ACTIVE:
        return company  # déjà provisionnée : rien à faire

    company.status = CompanyStatus.PROVISIONING
    company.save(update_fields=["status"])
    audit_service.log(ActionsAudit.PROVISION_STARTED, company=company)

    deja_franchies = ORDRE_ETAPES.index(job.step) if (job and job.step in ORDRE_ETAPES) else -1
    base_creee_ici = False

    try:
        if deja_franchies < ORDRE_ETAPES.index(ProvisionStep.CREATE_DB):
            base_creee_ici = creer_base(company.db_name)
            marquer(ProvisionStep.CREATE_DB)

        alias = _etape_migrate(company)
        marquer(ProvisionStep.MIGRATE)

        _etape_seed(company, alias)
        marquer(ProvisionStep.SEED)

        if mot_de_passe_hache is None:
            inscription = getattr(company, "signup", None)
            mot_de_passe_hache = inscription.password_hash if inscription else None
        _etape_owner(company, alias, mot_de_passe_hache)
        marquer(ProvisionStep.OWNER)

        _etape_domain(company)
        marquer(ProvisionStep.DOMAIN)

        _etape_done(company)
        marquer(ProvisionStep.DONE)

    except Exception as exc:
        logger.exception("Provisionnement de « %s » en échec", company.slug)
        # On ne détruit la base que si CETTE exécution l'a créée et que rien
        # n'y a encore été installé : au-delà, la reprise la termine.
        if base_creee_ici and (job is None or job.step in ("", ProvisionStep.CREATE_DB)):
            try:
                supprimer_base(company.db_name)
            except Exception:  # pragma: no cover
                logger.exception("Nettoyage de la base « %s » impossible", company.db_name)
        audit_service.log(
            ActionsAudit.PROVISION_FAILED, company=company,
            metadata={"erreur": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise EchecProvisionnement(str(exc)) from exc

    # Le mot de passe haché n'a plus lieu d'être conservé une fois le compte créé.
    inscription = getattr(company, "signup", None)
    if inscription is not None and inscription.password_hash:
        inscription.password_hash = ""
        inscription.save(update_fields=["password_hash"])

    audit_service.log(ActionsAudit.PROVISION_SUCCEEDED, company=company)
    return company


def mettre_en_file(company, *, priority=10):
    """Place un provisionnement en file d'attente et retourne le travail."""
    existant = ProvisioningJob.objects.filter(
        company=company, kind=JobKind.PROVISION,
        status__in=["QUEUED", "RUNNING"],
    ).first()
    if existant is not None:
        return existant

    job = ProvisioningJob.objects.create(
        company=company, kind=JobKind.PROVISION, priority=priority
    )
    audit_service.log(ActionsAudit.PROVISION_QUEUED, company=company)
    return job


def executer_job_provision(job):
    """Exécute un travail de provisionnement. Appelé par le moteur de travaux."""
    company = job.company
    if company is None:
        raise EchecProvisionnement("Travail de provisionnement sans entreprise.")

    provision(company, job=job)
    ticket = emettre_ticket_connexion(company)

    from saas.services.mail_service import queue_mail

    domaine = company.primary_domain
    queue_mail(
        "bienvenue",
        company.contact_email,
        {
            "entreprise": company.name,
            "identifiant": company.owner_username,
            "url": f"https://{domaine.hostname}" if domaine else "",
        },
        company=company,
        priority=5,
    )
    return {
        "slug": company.slug,
        "ticket_emis": bool(ticket),
        "at": timezone.now().isoformat(),
    }
