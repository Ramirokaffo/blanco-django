"""Constantes du plan de contrôle."""

from django.utils.translation import gettext_lazy as _

#: Sous-domaines interdits à l'inscription.
#:
#: Trois familles, toutes nécessaires :
#: - l'infrastructure de la plateforme (www, admin, api, static, media…) ;
#: - les noms techniques du courrier et du DNS, qu'un client ne doit jamais
#:   pouvoir détourner (mail, smtp, mx, autodiscover, _domainkey, dmarc…) ;
#: - les noms susceptibles de tromper un utilisateur (login, secure, billing,
#:   support…), qui serviraient à monter un hameçonnage crédible sur notre
#:   propre domaine.
SLUGS_RESERVES = frozenset({
    # Plateforme
    "www", "admin", "api", "app", "apps", "static", "media", "assets", "cdn",
    "files", "download", "downloads", "blanco", "public", "internal", "system",
    "console", "portal", "dashboard", "partner", "partners",
    # Environnements
    "dev", "staging", "test", "demo", "sandbox", "preprod", "prod",
    # Courrier et DNS
    "mail", "email", "smtp", "imap", "pop", "mx", "ns", "ns1", "ns2", "dns",
    "webmail", "autodiscover", "autoconfig", "_domainkey", "dmarc", "spf",
    "ftp", "vpn",
    # Comptes et paiement (risque d'hameçonnage)
    "account", "accounts", "auth", "login", "signup", "register", "secure",
    "ssl", "tls", "billing", "pay", "payment", "payments", "invoice",
    # Exploitation
    "status", "health", "monitoring", "metrics", "grafana", "prometheus",
    "backup", "backups", "db", "sql", "git", "support", "help", "docs", "doc",
    "blog", "shop", "store", "root", "my", "mobile", "m",
})

#: Durée de validité d'une invitation d'employé.
INVITATION_DUREE_JOURS = 7

#: Durée de validité du lien de vérification d'adresse à l'inscription.
VERIFICATION_DUREE_HEURES = 48

#: Durée de validité du ticket de connexion remis après le provisionnement.
#: Très court : il donne un accès authentifié sans mot de passe.
TICKET_CONNEXION_DUREE_MINUTES = 5

#: Délai au-delà duquel une inscription non vérifiée est purgée, libérant son
#: sous-domaine.
PURGE_INSCRIPTIONS_JOURS = 7

#: Nombre maximal de tentatives d'un travail avant abandon définitif.
JOB_TENTATIVES_MAX = 3

#: Paliers d'attente entre deux tentatives (secondes).
JOB_BACKOFF_SECONDES = (30, 120, 600)

#: Durée du bail d'un travail en cours. Au-delà, il est considéré comme
#: abandonné (processus tué) et remis en file avec son point de reprise.
JOB_BAIL_SECONDES = 600


class ActionsAudit:
    """Actions consignées dans le journal d'audit de la plateforme."""

    SIGNUP_CREATED = "SIGNUP_CREATED"
    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    PROVISION_QUEUED = "PROVISION_QUEUED"
    PROVISION_STARTED = "PROVISION_STARTED"
    PROVISION_SUCCEEDED = "PROVISION_SUCCEEDED"
    PROVISION_FAILED = "PROVISION_FAILED"
    COMPANY_SUSPENDED = "COMPANY_SUSPENDED"
    COMPANY_REACTIVATED = "COMPANY_REACTIVATED"
    DELETION_SCHEDULED = "DELETION_SCHEDULED"
    DELETION_CANCELLED = "DELETION_CANCELLED"
    COMPANY_DELETED = "COMPANY_DELETED"
    INVITATION_SENT = "INVITATION_SENT"
    INVITATION_ACCEPTED = "INVITATION_ACCEPTED"
    INVITATION_REVOKED = "INVITATION_REVOKED"
    DOMAIN_ADDED = "DOMAIN_ADDED"
    DOMAIN_VERIFIED = "DOMAIN_VERIFIED"
    DOMAIN_REMOVED = "DOMAIN_REMOVED"
    PLATFORM_LOGIN = "PLATFORM_LOGIN"
    PLATFORM_LOGIN_FAILED = "PLATFORM_LOGIN_FAILED"
    PLAN_CHANGED = "PLAN_CHANGED"
    MAIL_SENT = "MAIL_SENT"
    MAIL_FAILED = "MAIL_FAILED"

    CHOICES = [
        (SIGNUP_CREATED, _("Inscription créée")),
        (EMAIL_VERIFIED, _("Adresse vérifiée")),
        (PROVISION_QUEUED, _("Création mise en file")),
        (PROVISION_STARTED, _("Création démarrée")),
        (PROVISION_SUCCEEDED, _("Création réussie")),
        (PROVISION_FAILED, _("Création échouée")),
        (COMPANY_SUSPENDED, _("Espace suspendu")),
        (COMPANY_REACTIVATED, _("Espace réactivé")),
        (DELETION_SCHEDULED, _("Suppression programmée")),
        (DELETION_CANCELLED, _("Suppression annulée")),
        (COMPANY_DELETED, _("Espace supprimé")),
        (INVITATION_SENT, _("Invitation envoyée")),
        (INVITATION_ACCEPTED, _("Invitation acceptée")),
        (INVITATION_REVOKED, _("Invitation révoquée")),
        (DOMAIN_ADDED, _("Nom d'hôte ajouté")),
        (DOMAIN_VERIFIED, _("Nom d'hôte vérifié")),
        (DOMAIN_REMOVED, _("Nom d'hôte retiré")),
        (PLATFORM_LOGIN, _("Connexion à la plateforme")),
        (PLATFORM_LOGIN_FAILED, _("Échec de connexion à la plateforme")),
        (PLAN_CHANGED, _("Changement d'offre")),
        (MAIL_SENT, _("E-mail envoyé")),
        (MAIL_FAILED, _("Échec d'envoi d'e-mail")),
    ]
