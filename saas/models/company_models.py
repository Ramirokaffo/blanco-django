"""
Entreprises clientes et noms d'hôtes qui les désignent.

Frontière de responsabilité — à respecter scrupuleusement
---------------------------------------------------------
``Company`` porte ce dont **la plateforme** a besoin pour router, exploiter et
assister : identité de compte, base de données, état, contact technique.

``core.SystemSettings`` (dans la base de la société) porte tout ce qui
s'**imprime sur un document** commercial ou fiscal : nom commercial, logo,
adresse, NIF, RCCM, devise, mentions des reçus, régime de TVA.

Le NIF et le RCCM ne sont donc **jamais** recopiés ici : la plateforme n'a
aucune raison de détenir les données fiscales de ses clients.

``Company.name`` est recopié dans ``SystemSettings.company_name`` **une seule
fois**, au provisionnement. Ensuite les deux valeurs divergent librement : le
client renomme sa boutique sans que cela change la raison sociale de son
compte. Cette divergence est le comportement attendu, pas une incohérence à
resynchroniser.
"""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models.base_models import SoftDeleteModel
from saas.db import alias_for


class CompanyStatus(models.TextChoices):
    """Cycle de vie d'un espace client."""

    PENDING_VERIFICATION = "PENDING_VERIFICATION", _("En attente de vérification")
    PROVISIONING = "PROVISIONING", _("Création en cours")
    ACTIVE = "ACTIVE", _("Actif")
    SUSPENDED = "SUSPENDED", _("Suspendu")
    PROVISION_FAILED = "PROVISION_FAILED", _("Échec de création")
    SCHEDULED_DELETION = "SCHEDULED_DELETION", _("Suppression programmée")
    DELETED = "DELETED", _("Supprimé")


class DomainKind(models.TextChoices):
    SUBDOMAIN = "SUBDOMAIN", _("Sous-domaine de la plateforme")
    CUSTOM = "CUSTOM", _("Domaine propre du client")


class TlsStatus(models.TextChoices):
    NONE = "NONE", _("Sans certificat")
    PENDING = "PENDING", _("Certificat en cours d'obtention")
    ISSUED = "ISSUED", _("Certificat délivré")
    FAILED = "FAILED", _("Échec d'obtention")


class Company(SoftDeleteModel):
    """Une entreprise cliente de la plateforme, et sa base de données."""

    name = models.CharField(
        max_length=200,
        verbose_name=_("Raison sociale"),
        help_text=_(
            "Libellé utilisé par la plateforme. Le nom imprimé sur les reçus "
            "se règle dans les paramètres de l'espace."
        ),
    )
    slug = models.SlugField(
        max_length=40,
        unique=True,
        verbose_name=_("Sous-domaine"),
        help_text=_("Identifiant de l'espace : <sous-domaine>.exemple.com"),
    )

    # ──── Base de données ───────────────────────────────────────────────
    db_name = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("Nom de la base de données"),
    )
    db_host = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name=_("Serveur de base de données"),
        help_text=_("Vide : le serveur par défaut. Permet de répartir les sociétés."),
    )

    # ──── Cycle de vie ──────────────────────────────────────────────────
    status = models.CharField(
        max_length=25,
        choices=CompanyStatus.choices,
        default=CompanyStatus.PENDING_VERIFICATION,
        db_index=True,
        verbose_name=_("État"),
    )
    provisioned_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Créé le")
    )
    suspended_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Suspendu le")
    )
    suspended_reason = models.TextField(
        blank=True, default="", verbose_name=_("Motif de suspension")
    )
    deletion_scheduled_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Suppression prévue le")
    )

    # ──── Contact du compte ─────────────────────────────────────────────
    contact_email = models.EmailField(
        verbose_name=_("E-mail du titulaire du compte"),
        help_text=_(
            "Adresse du responsable de l'abonnement. Distincte de l'e-mail "
            "public de la boutique, réglé dans les paramètres de l'espace."
        ),
    )
    contact_name = models.CharField(
        max_length=150, blank=True, default="", verbose_name=_("Nom du contact")
    )
    contact_phone = models.CharField(
        max_length=50, blank=True, default="", verbose_name=_("Téléphone du contact")
    )
    language = models.CharField(
        max_length=5, default="fr", verbose_name=_("Langue"),
        help_text=_("Langue des messages envoyés par la plateforme."),
    )

    # ──── Propriétaire, côté base société ───────────────────────────────
    # Clé étrangère *logique* : la ligne visée vit dans une AUTRE base, aucune
    # contrainte d'intégrité n'est donc possible.
    owner_user_id = models.IntegerField(
        null=True, blank=True, verbose_name=_("Identifiant du propriétaire")
    )
    owner_username = models.CharField(
        max_length=150, blank=True, default="",
        verbose_name=_("Identifiant de connexion du propriétaire"),
    )

    # ──── Offre ─────────────────────────────────────────────────────────
    plan = models.ForeignKey(
        "saas.Plan",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="companies",
        verbose_name=_("Offre"),
    )
    trial_ends_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Fin de la période d'essai")
    )

    class Meta:
        db_table = "saas_company"
        verbose_name = _("Entreprise")
        verbose_name_plural = _("Entreprises")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    # ──── Accès ─────────────────────────────────────────────────────────

    @property
    def db_alias(self) -> str:
        """Alias Django de la base de cette entreprise."""
        return alias_for(self.pk)

    @property
    def is_reachable(self) -> bool:
        """
        Vrai si l'espace peut servir des requêtes.

        Un espace suspendu ou en cours de création reste résolu (pour afficher
        un écran d'explication), mais n'est pas joignable.
        """
        return self.status == CompanyStatus.ACTIVE and self.delete_at is None

    @property
    def primary_domain(self):
        """Nom d'hôte principal, ou ``None`` si aucun n'est encore rattaché."""
        return self.domains.filter(is_primary=True).first()

    def suspend(self, reason: str):
        self.status = CompanyStatus.SUSPENDED
        self.suspended_at = timezone.now()
        self.suspended_reason = reason
        self.save(update_fields=["status", "suspended_at", "suspended_reason"])

    def reactivate(self):
        self.status = CompanyStatus.ACTIVE
        self.suspended_at = None
        self.suspended_reason = ""
        self.save(update_fields=["status", "suspended_at", "suspended_reason"])


class Domain(models.Model):
    """
    Nom d'hôte désignant un espace client.

    Chaque entreprise en a au moins un (son sous-domaine) et peut y ajouter un
    domaine propre. C'est **cette table qui fait office de liste blanche
    d'hôtes** : le middleware refuse tout nom d'hôte absent d'ici, ce qui est
    plus strict qu'``ALLOWED_HOSTS`` puisque adossé à des données réelles.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="domains",
        verbose_name=_("Entreprise"),
    )
    hostname = models.CharField(
        max_length=253, unique=True, verbose_name=_("Nom d'hôte")
    )
    kind = models.CharField(
        max_length=10,
        choices=DomainKind.choices,
        default=DomainKind.SUBDOMAIN,
        verbose_name=_("Type"),
    )
    is_primary = models.BooleanField(default=False, verbose_name=_("Principal"))
    is_verified = models.BooleanField(default=False, verbose_name=_("Vérifié"))
    verification_token = models.CharField(
        max_length=64, blank=True, default="",
        verbose_name=_("Jeton de vérification DNS"),
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Vérifié le")
    )
    tls_status = models.CharField(
        max_length=10,
        choices=TlsStatus.choices,
        default=TlsStatus.NONE,
        verbose_name=_("État du certificat"),
    )
    create_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_domain"
        verbose_name = _("Nom d'hôte")
        verbose_name_plural = _("Noms d'hôte")
        ordering = ["-is_primary", "hostname"]
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_primary=True),
                name="un_seul_domaine_principal_par_entreprise",
            )
        ]

    def __str__(self):
        return self.hostname

    def clean(self):
        # Les noms d'hôte sont insensibles à la casse : on normalise pour que
        # la contrainte d'unicité et la résolution portent sur la même valeur.
        if self.hostname:
            self.hostname = self.hostname.strip().lower().rstrip(".")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
