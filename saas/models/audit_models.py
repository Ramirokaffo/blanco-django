"""
Journal d'audit de la plateforme, en **ajout seul**.

Ce journal doit pouvoir servir de trace probante : qui a suspendu quel espace,
quand, et pour quel motif. Il est donc volontairement non modifiable et non
supprimable, y compris depuis l'administration.

Les identifiants d'acteur et d'entreprise sont **dénormalisés** (``actor_label``,
``company_slug``) : un compte peut être supprimé, un espace peut disparaître,
mais la trace de ce qui s'est produit doit rester lisible des années plus tard.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from saas.constants import ActionsAudit


class ActorKind(models.TextChoices):
    PLATFORM_STAFF = "PLATFORM_STAFF", _("Équipe plateforme")
    TENANT_OWNER = "TENANT_OWNER", _("Propriétaire de l'espace")
    TENANT_USER = "TENANT_USER", _("Utilisateur de l'espace")
    SYSTEM = "SYSTEM", _("Automatique")


class JournalEnAjoutSeulError(RuntimeError):
    """Tentative de modifier ou supprimer une ligne du journal d'audit."""


class PlatformAuditLog(models.Model):
    """Une action consignée. Jamais modifiée, jamais supprimée."""

    create_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor_kind = models.CharField(
        max_length=20, choices=ActorKind.choices, default=ActorKind.SYSTEM,
        verbose_name=_("Type d'acteur"),
    )
    actor_id = models.IntegerField(null=True, blank=True)
    actor_label = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("Acteur"),
        help_text=_("Conservé en clair : l'acteur peut disparaître."),
    )

    company = models.ForeignKey(
        "saas.Company",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="audit_entries",
        verbose_name=_("Entreprise"),
    )
    company_slug = models.CharField(
        max_length=40, blank=True, default="",
        help_text=_("Conservé en clair : survit à la suppression de l'espace."),
    )

    action = models.CharField(
        max_length=60, choices=ActionsAudit.CHOICES, db_index=True,
        verbose_name=_("Action"),
    )
    target = models.CharField(max_length=200, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        db_table = "saas_platform_audit_log"
        verbose_name = _("Entrée du journal d'audit")
        verbose_name_plural = _("Journal d'audit")
        ordering = ["-create_at"]

    def __str__(self):
        return f"{self.create_at:%Y-%m-%d %H:%M} · {self.action} · {self.company_slug}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise JournalEnAjoutSeulError(
                "Le journal d'audit est en ajout seul : une entrée existante "
                "ne peut pas être modifiée."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise JournalEnAjoutSeulError(
            "Le journal d'audit est en ajout seul : une entrée ne peut pas "
            "être supprimée."
        )
