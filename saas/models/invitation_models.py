"""
Inscriptions en attente et invitations d'employés.

Principe commun aux deux : **le jeton en clair n'est jamais stocké.** Seule son
empreinte SHA-256 est enregistrée. Le clair n'existe que dans le lien envoyé
par e-mail. Une fuite de la base de la plateforme ne permet donc ni de valider
une inscription, ni de forger l'acceptation d'une invitation.
"""

import hashlib
import secrets

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models.base_models import SoftDeleteModel

#: Longueur des jetons, en octets avant encodage.
LONGUEUR_JETON = 32


def generer_jeton() -> str:
    """Jeton aléatoire adapté à une URL."""
    return secrets.token_urlsafe(LONGUEUR_JETON)


def empreinte(jeton: str) -> str:
    """Empreinte stockée en base. Jamais le jeton lui-même."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


class InvitationStatus(models.TextChoices):
    PENDING = "PENDING", _("En attente")
    ACCEPTED = "ACCEPTED", _("Acceptée")
    EXPIRED = "EXPIRED", _("Expirée")
    REVOKED = "REVOKED", _("Révoquée")


class SignupRequest(models.Model):
    """
    Inscription en attente de vérification d'adresse.

    L'entreprise est créée **dès l'inscription** (au statut
    ``PENDING_VERIFICATION``), et non après la vérification. Motif : le
    sous-domaine doit être réservé immédiatement, et on refuse d'avoir deux
    sources de vérité pour son unicité. Une seule contrainte, sur une seule
    table. Les inscriptions jamais confirmées sont purgées au bout de quelques
    jours, ce qui libère le sous-domaine.
    """

    company = models.OneToOneField(
        "saas.Company",
        on_delete=models.CASCADE,
        related_name="signup",
        verbose_name=_("Entreprise"),
    )
    email = models.EmailField(verbose_name=_("Adresse à vérifier"))

    # Mot de passe haché dès la saisie : le clair ne persiste jamais, pas même
    # une seconde. Effacé une fois le compte propriétaire créé.
    password_hash = models.CharField(max_length=128, blank=True, default="")

    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField(verbose_name=_("Expire le"))
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Vérifiée le"))

    # Ticket à usage unique remis après le provisionnement : il connecte le
    # propriétaire sans qu'il ait à ressaisir son mot de passe. Très court.
    login_ticket_hash = models.CharField(max_length=64, blank=True, default="")
    login_ticket_expires_at = models.DateTimeField(null=True, blank=True)
    login_ticket_used_at = models.DateTimeField(null=True, blank=True)

    send_count = models.PositiveIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    create_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_signup_request"
        verbose_name = _("Inscription")
        verbose_name_plural = _("Inscriptions")
        ordering = ["-create_at"]

    def __str__(self):
        return f"{self.email} → {self.company.slug}"

    @property
    def est_expiree(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def est_verifiee(self) -> bool:
        return self.verified_at is not None

    def correspond_au_jeton(self, jeton: str) -> bool:
        return bool(jeton) and secrets.compare_digest(self.token_hash, empreinte(jeton))

    def ticket_valide(self, ticket: str) -> bool:
        """Le ticket de connexion est à usage unique et de courte durée."""
        if not self.login_ticket_hash or self.login_ticket_used_at is not None:
            return False
        if not self.login_ticket_expires_at or timezone.now() >= self.login_ticket_expires_at:
            return False
        return secrets.compare_digest(self.login_ticket_hash, empreinte(ticket or ""))


class Invitation(SoftDeleteModel):
    """
    Invitation d'un employé à rejoindre l'espace d'une entreprise.

    ``module_codes`` est une liste de **codes**, pas une relation vers
    ``core.AppModule`` : ces lignes vivent dans *chaque* base société, avec des
    clés primaires différentes d'une société à l'autre. Une relation pointerait
    vers une table absente de la base plateforme. Les codes de
    ``DEFAULT_MODULES`` sont, eux, stables et partagés — ce sont eux la clé
    fonctionnelle.
    """

    company = models.ForeignKey(
        "saas.Company",
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name=_("Entreprise"),
    )
    email = models.EmailField(verbose_name=_("Adresse de l'employé"))
    firstname = models.CharField(max_length=150, blank=True, default="", verbose_name=_("Prénom"))
    lastname = models.CharField(max_length=150, blank=True, default="", verbose_name=_("Nom"))
    role = models.CharField(max_length=50, blank=True, default="", verbose_name=_("Rôle"))

    module_codes = models.JSONField(
        default=list, blank=True, verbose_name=_("Modules attribués")
    )

    token_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=10, choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING, verbose_name=_("État"),
    )
    expires_at = models.DateTimeField(verbose_name=_("Expire le"))

    # Clés étrangères *logiques* : les comptes visés vivent dans la base de la
    # société, aucune contrainte d'intégrité n'est donc possible.
    invited_by_user_id = models.IntegerField(null=True, blank=True)
    invited_by_label = models.CharField(max_length=150, blank=True, default="")
    accepted_user_id = models.IntegerField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    send_count = models.PositiveIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "saas_invitation"
        verbose_name = _("Invitation")
        verbose_name_plural = _("Invitations")
        ordering = ["-create_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "email"],
                condition=models.Q(status="PENDING"),
                name="une_invitation_en_cours_par_adresse",
            )
        ]

    def __str__(self):
        return f"{self.email} → {self.company.slug} [{self.status}]"

    @property
    def est_expiree(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def est_utilisable(self) -> bool:
        return self.status == InvitationStatus.PENDING and not self.est_expiree

    def correspond_au_jeton(self, jeton: str) -> bool:
        return bool(jeton) and secrets.compare_digest(self.token_hash, empreinte(jeton))
