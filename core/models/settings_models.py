"""
System settings model for storing configurable application parameters.
"""

from django.db import models


# ──────────────────────────────────────────────────────────────────────────────
# Modules applicatifs — chaque entrée correspond à un onglet / fonctionnalité
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_MODULES = [
    ('dashboard',    'Tableau de bord',    '📊', 1),
    ('sales',        'Ventes',             '🛒', 2),
    ('products',     'Produits',           '📦', 3),
    ('suppliers',    'Fournisseurs',       '🤝', 4),
    ('supplies',     'Approvisionnement',  '🚚', 5),
    ('expenses',     'Dépenses',           '💰', 6),
    ('contacts',     'Utilisateurs',       '👥', 7),
    ('inventory',    'Inventaire',         '📋', 8),
    ('accounting',   'Comptabilité',       '📒', 9),
    ('treasury',     'Trésorerie',         '🏦', 10),
    ('reports',      'Rapports',           '📄', 11),
    ('settings',     'Paramètres',         '⚙️', 12),
]


class AppModule(models.Model):
    """
    Module applicatif (onglet / fonctionnalité).
    Chaque module peut être activé ou désactivé par utilisateur.
    """
    code = models.CharField(
        max_length=50, unique=True,
        verbose_name="Code du module",
        help_text="Identifiant technique (ex: sales, products, accounting)"
    )
    name = models.CharField(
        max_length=100, verbose_name="Nom affiché"
    )
    icon = models.CharField(
        max_length=10, blank=True, default="",
        verbose_name="Icône (emoji)"
    )
    order = models.PositiveIntegerField(
        default=0, verbose_name="Ordre d'affichage"
    )
    is_active = models.BooleanField(
        default=True, verbose_name="Module actif",
        help_text="Si désactivé, le module n'est visible pour personne"
    )

    class Meta:
        db_table = 'app_module'
        verbose_name = 'Module applicatif'
        verbose_name_plural = 'Modules applicatifs'
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.icon} {self.name}" if self.icon else self.name

    @classmethod
    def init_default_modules(cls):
        """Crée les modules par défaut s'ils n'existent pas."""
        created = 0
        for code, name, icon, order in DEFAULT_MODULES:
            _, was_created = cls.objects.get_or_create(
                code=code,
                defaults={'name': name, 'icon': icon, 'order': order}
            )
            if was_created:
                created += 1
        return created


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

    # ──── Paramètres d'approvisionnement ────────────────────────────────────
    default_supply_expense_type = models.ForeignKey(
        'core.ExpenseType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Type de dépense par défaut pour les approvisionnements"
    )

    # ──── Paramètres de TVA ─────────────────────────────────────────────────
    TVA_ACCOUNTING_MODE_CHOICES = [
        ('IMMEDIATE', 'Immédiat - À chaque vente'),
        ('DEFERRED', 'Différé - En fin de journée (clôture du Daily)'),
    ]
    tva_accounting_mode = models.CharField(
        max_length=20,
        choices=TVA_ACCOUNTING_MODE_CHOICES,
        default='IMMEDIATE',
        verbose_name="Mode d'enregistrement de la TVA",
        help_text="Immédiat : écritures TVA créées à chaque vente. Différé : écritures créées à la clôture du Daily."
    )
    enable_tva_accounting = models.BooleanField(
        default=True,
        verbose_name="Activer la comptabilité TVA",
        help_text="Activer l'enregistrement des écritures de TVA sur les ventes"
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

