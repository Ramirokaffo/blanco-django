"""Configuration de l'application du plan de contrôle."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class SaasConfig(AppConfig):
    name = "saas"
    verbose_name = _("Plateforme")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from saas.signals import seed_platform_data

        # Estampille de session : voir saas/signals.py.
        from saas import signals  # noqa: F401

        # Offres par défaut, après chaque migrate de cette application.
        post_migrate.connect(
            seed_platform_data,
            sender=self,
            dispatch_uid="saas.seed_platform_data",
        )
