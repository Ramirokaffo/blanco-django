"""Signaux du plan de contrôle."""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from saas.context import get_current_key
from saas.middleware import TENANT_SESSION_KEY


@receiver(user_logged_in, dispatch_uid="saas.estampiller_session")
def estampiller_session(sender, request, user, **kwargs):
    """
    Marque la session avec la société où la connexion a eu lieu.

    ``TenantSessionGuardMiddleware`` s'en sert pour rejeter une session
    présentée sur l'espace d'une autre entreprise.
    """
    cle = get_current_key()
    if cle and hasattr(request, "session"):
        request.session[TENANT_SESSION_KEY] = cle


def seed_platform_data(sender, **kwargs):
    """
    Crée les offres par défaut après un ``migrate`` de l'application ``saas``.

    Même mécanique que ``core.signals.seed_default_data`` : l'alias réellement
    migré est transmis par le signal et doit être propagé.

    Nuance propre au plan de contrôle : ``post_migrate`` se déclenche pour
    **chaque** base migrée, y compris celle d'une société. Or les tables de
    ``saas`` n'existent que dans la base plateforme. On interroge donc le
    routeur plutôt que de coder « default » en dur : si la règle de routage
    évolue un jour, ce garde reste juste.
    """
    from django.db import router

    from saas.models import init_default_plans

    using = kwargs.get("using")
    if using and not router.allow_migrate(using, "saas"):
        return

    crees = init_default_plans(using=using)

    if kwargs.get("verbosity", 1) >= 1 and crees:
        print(f"✅ Plateforme : {crees} offre(s) créée(s).")
