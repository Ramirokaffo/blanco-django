"""
System settings model for storing configurable application parameters.
"""

from django.db import models


class SystemSettings(models.Model):
    """
    Modèle singleton pour stocker les paramètres système de l'application.
    Une seule instance est autorisée (pk=1).
    """

    # ──── Informations de l'entreprise ─────────────────────────────────
    company_name = models.CharField(
        max_length=200, default="BLANCO", verbose_name="Nom de l'entreprise"
    )
    company_address = models.TextField(
        blank=True, default="", verbose_name="Adresse de l'entreprise"
    )
    company_phone = models.CharField(
        max_length=50, blank=True, default="", verbose_name="Téléphone"
    )
    company_email = models.EmailField(
        blank=True, default="", verbose_name="Email"
    )
    company_website = models.URLField(
        blank=True, default="", verbose_name="Site web"
    )
    company_logo = models.ImageField(
        upload_to="settings/logo/", blank=True, null=True, verbose_name="Logo"
    )

    # ──── Informations fiscales / légales ──────────────────────────────
    tax_id = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name="Numéro d'identification fiscale (NIF)"
    )
    trade_register = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name="Registre de commerce (RCCM)"
    )

    # ──── Paramètres monétaires ────────────────────────────────────────
    currency_symbol = models.CharField(
        max_length=10, default="FCFA", verbose_name="Symbole monétaire"
    )
    currency_code = models.CharField(
        max_length=5, default="XAF", verbose_name="Code devise (ISO 4217)"
    )

    # ──── Paramètres de tickets / reçus ────────────────────────────────
    receipt_header = models.TextField(
        blank=True, default="",
        verbose_name="En-tête du reçu",
        help_text="Texte affiché en haut des reçus/tickets"
    )
    receipt_footer = models.TextField(
        blank=True, default="Merci pour votre achat !",
        verbose_name="Pied de page du reçu",
        help_text="Texte affiché en bas des reçus/tickets"
    )

    # ──── Paramètres de stock ──────────────────────────────────────────
    low_stock_threshold = models.PositiveIntegerField(
        default=10,
        verbose_name="Seuil d'alerte stock bas",
        help_text="Quantité en dessous de laquelle une alerte est déclenchée"
    )

    # ──── Métadonnées ──────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")

    class Meta:
        verbose_name = "Paramètres Système"
        verbose_name_plural = "Paramètres Système"
        db_table = "system_settings"

    def __str__(self):
        return f"Paramètres système - {self.company_name}"

    @classmethod
    def get_settings(cls):
        """Récupère les paramètres système (crée une instance par défaut si nécessaire)."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """S'assurer qu'il n'y a qu'une seule instance de paramètres."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Empêcher la suppression de l'instance unique."""
        pass

