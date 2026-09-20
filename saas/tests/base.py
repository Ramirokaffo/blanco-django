"""
Socle commun des tests d'isolation.

Les alias ``tenant_1001`` et ``tenant_1002`` sont déclarés statiquement dans
``blanco/settings.py`` lorsque ``BLANCO_MODE=saas`` et que la commande est
``test`` : le lanceur de Django crée donc leurs bases de test comme celle de
``default``. Sous SQLite, ce sont des bases distinctes — ces tests tournent
sans serveur MySQL.
"""

from django.test import TestCase, override_settings

from saas.models import Company, CompanyStatus, Domain, DomainKind

#: Cache mémoire (pas de serveur Redis requis) MAIS avec la fonction de clé
#: du mode SaaS : c'est bien le cloisonnement des clés que l'on veut éprouver.
CACHES_DE_TEST = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "isolation-tests",
        "KEY_PREFIX": "blanco",
        "KEY_FUNCTION": "saas.cache.tenant_key_func",
    }
}


def parametres_saas(**extra):
    """Décorateur activant le mode SaaS complet pour une classe de test."""
    reglages = {
        "IS_SAAS": True,
        "BLANCO_PLATFORM_DOMAIN": "blanco.test",
        "DATABASE_ROUTERS": ["saas.routers.TenantRouter"],
        "BLANCO_STRICT_TENANT": False,
        "CACHES": CACHES_DE_TEST,
        "STATICFILES_STORAGE": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }
    reglages.update(extra)
    return override_settings(**reglages)


#: Clés primaires des entreprises factices. Elles doivent correspondre aux
#: alias déclarés dans blanco/settings.py (TENANT_TEST_IDS), car l'alias d'une
#: société est dérivé de sa clé primaire.
ID_SOCIETE_A = 1001
ID_SOCIETE_B = 1002

ALIAS_A = f"tenant_{ID_SOCIETE_A}"
ALIAS_B = f"tenant_{ID_SOCIETE_B}"


def parametres_tenant(**extra):
    """
    Comme ``parametres_saas``, mais avec l'URLconf des espaces clients.

    ``reverse()`` appelé hors requête s'appuie sur ``ROOT_URLCONF``, qui vaut
    l'URLconf de la plateforme en mode SaaS. Les tests portant sur les pages
    d'un espace doivent donc la basculer — c'est ce que fait le middleware à
    chaque requête réelle.
    """
    reglages = {"ROOT_URLCONF": "blanco.urls_tenant"}
    reglages.update(extra)
    return parametres_saas(**reglages)


class IsolationTestCase(TestCase):
    """
    Base des tests manipulant plusieurs sociétés.

    ``databases`` doit lister explicitement les alias : par défaut, un
    ``TestCase`` Django n'ouvre que ``default`` et toute autre base lèverait
    une erreur d'accès interdit.
    """

    databases = {"default", ALIAS_A, ALIAS_B}

    @staticmethod
    def creer_entreprise(pk, slug, nom=None, statut=CompanyStatus.ACTIVE):
        """
        Crée une entreprise du plan de contrôle rattachée à un alias de test.

        L'alias d'une société est dérivé de sa clé primaire
        (``tenant_<pk>``) : on force donc des pk correspondant aux alias
        déclarés dans les réglages de test.
        """
        entreprise = Company.objects.create(
            pk=pk,
            name=nom or slug.upper(),
            slug=slug,
            db_name=f"blanco_t_{slug}",
            status=statut,
            contact_email=f"contact@{slug}.test",
        )
        Domain.objects.create(
            company=entreprise,
            hostname=f"{slug}.blanco.test",
            kind=DomainKind.SUBDOMAIN,
            is_primary=True,
            is_verified=True,
        )
        return entreprise
