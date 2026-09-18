"""
System settings model for storing configurable application parameters.
"""

from django.db import models
from django.utils.translation import gettext, gettext_lazy as _, gettext_noop


# ──────────────────────────────────────────────────────────────────────────────
# Modules applicatifs — chaque entrée correspond à un onglet / fonctionnalité
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_MODULES = [
    ('dashboard',    gettext_noop('Tableau de bord'),    '📊', 1),
    ('sales',        gettext_noop('Ventes'),             '🛒', 2),
    ('products',     gettext_noop('Produits'),           '📦', 3),
    ('suppliers',    gettext_noop('Fournisseurs'),       '🤝', 4),
    ('supplies',     gettext_noop('Approvisionnement'),  '🚚', 5),
    ('expenses',     gettext_noop('Dépenses'),           '💰', 6),
    ('contacts',     gettext_noop('Utilisateurs'),       '👥', 7),
    ('inventory',    gettext_noop('Inventaire'),         '📋', 8),
    ('accounting',   gettext_noop('Comptabilité'),       '📒', 9),
    ('treasury',     gettext_noop('Trésorerie'),         '🏦', 10),
    ('reports',      gettext_noop('Rapports'),           '📄', 11),
    ('settings',     gettext_noop('Paramètres'),         '⚙️', 12),
]


class AppModule(models.Model):
    """
    Module applicatif (onglet / fonctionnalité).
    Chaque module peut être activé ou désactivé par utilisateur.
    """
    code = models.CharField(
        max_length=50, unique=True,
        verbose_name=_("Code du module"),
        help_text=_("Identifiant technique (ex: sales, products, accounting)")
    )
    name = models.CharField(
        max_length=100, verbose_name=_("Nom affiché")
    )
    icon = models.CharField(
        max_length=10, blank=True, default="",
        verbose_name=_("Icône (emoji)")
    )
    order = models.PositiveIntegerField(
        default=0, verbose_name=_("Ordre d'affichage")
    )
    is_active = models.BooleanField(
        default=True, verbose_name=_("Module actif"),
        help_text=_("Si désactivé, le module n'est visible pour personne")
    )

    class Meta:
        db_table = 'app_module'
        verbose_name = _('Module applicatif')
        verbose_name_plural = _('Modules applicatifs')
        ordering = ['order', 'name']

    def __str__(self):
        name = gettext(self.name)
        return f"{self.icon} {name}" if self.icon else name

    @classmethod
    def init_default_modules(cls):
        """Crée les modules par défaut s'ils n'existent pas."""
        created = 0
        for code, name, icon, order in DEFAULT_MODULES:
            _module, was_created = cls.objects.get_or_create(
                code=code,
                defaults={'name': name, 'icon': icon, 'order': order}
            )
            if was_created:
                created += 1
        return created

    @classmethod
    def sync_default_modules(cls):
        """
        Réaligne le nom, l'icône et l'ordre des modules existants sur DEFAULT_MODULES.
        Ne touche ni à `is_active` ni aux attributions par utilisateur.
        Retourne le nombre de modules modifiés.
        """
        updated = 0
        for code, name, icon, order in DEFAULT_MODULES:
            changed = cls.objects.filter(code=code).exclude(
                name=name, icon=icon, order=order
            ).update(name=name, icon=icon, order=order)
            updated += changed
        return updated


class SystemSettings(models.Model):
    """
    Modèle singleton pour stocker les paramètres système de l'application.
    Une seule instance est autorisée (pk=1).
    """

    # ──── Informations de l'entreprise ─────────────────────────────────
    company_name = models.CharField(
        max_length=200, default="BLANCO", verbose_name=_("Nom de l'entreprise")
    )
    company_address = models.TextField(
        blank=True, default="", verbose_name=_("Adresse de l'entreprise")
    )
    company_phone = models.CharField(
        max_length=50, blank=True, default="", verbose_name=_("Téléphone")
    )
    company_email = models.EmailField(
        blank=True, default="", verbose_name=_("Email")
    )
    company_website = models.URLField(
        blank=True, default="", verbose_name=_("Site web")
    )
    company_logo = models.ImageField(
        upload_to="settings/logo/", blank=True, null=True, verbose_name=_("Logo")
    )

    # ──── Informations fiscales / légales ──────────────────────────────
    tax_id = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name=_("Numéro d'identification fiscale (NIF)")
    )
    trade_register = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name=_("Registre de commerce (RCCM)")
    )

    # ──── Paramètres monétaires ────────────────────────────────────────
    currency_symbol = models.CharField(
        max_length=10, default="FCFA", verbose_name=_("Symbole monétaire")
    )
    currency_code = models.CharField(
        max_length=5, default="XAF", verbose_name=_("Code devise (ISO 4217)")
    )

    # ──── Paramètres de tickets / reçus ────────────────────────────────
    receipt_header = models.TextField(
        blank=True, default="",
        verbose_name=_("En-tête du reçu"),
        help_text=_("Texte affiché en haut des reçus/tickets")
    )
    receipt_footer = models.TextField(
        blank=True, default="Merci pour votre achat !",
        verbose_name=_("Pied de page du reçu"),
        help_text=_("Texte affiché en bas des reçus/tickets")
    )

    # ──── Paramètres de stock ──────────────────────────────────────────
    low_stock_threshold = models.PositiveIntegerField(
        default=10,
        verbose_name=_("Seuil d'alerte stock bas"),
        help_text=_("Quantité en dessous de laquelle une alerte est déclenchée")
    )

    # ──── Paramètres d'approvisionnement ────────────────────────────────────
    default_supply_expense_type = models.ForeignKey(
        'core.ExpenseType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_("Type de dépense par défaut pour les approvisionnements")
    )

    # ──── Paramètres de TVA ─────────────────────────────────────────────────
    TVA_ACCOUNTING_MODE_CHOICES = [
        ('IMMEDIATE', _('Immédiat - À chaque vente')),
        ('DEFERRED', _('Différé - En fin de journée (clôture du Daily)')),
    ]
    tva_accounting_mode = models.CharField(
        max_length=20,
        choices=TVA_ACCOUNTING_MODE_CHOICES,
        default='IMMEDIATE',
        verbose_name=_("Mode d'enregistrement de la TVA"),
        help_text=_("Immédiat : écritures TVA créées à chaque vente. Différé : écritures créées à la clôture du Daily.")
    )
    enable_tva_accounting = models.BooleanField(
        default=True,
        verbose_name=_("Activer la comptabilité TVA"),
        help_text=_("Activer l'enregistrement des écritures de TVA sur les ventes")
    )

    # ──── Métadonnées ──────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Dernière modification"))

    class Meta:
        verbose_name = _("Paramètres Système")
        verbose_name_plural = _("Paramètres Système")
        db_table = "system_settings"

    def __str__(self):
        return gettext("Paramètres système - %(company)s") % {'company': self.company_name}

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

