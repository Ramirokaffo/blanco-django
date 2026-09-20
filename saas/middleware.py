"""
Middlewares du mode SaaS : résolution de l'entreprise, garde de session.

``TenantMiddleware`` est placé **en tête** de la pile (juste après
``SecurityMiddleware``) pour deux raisons :

* il valide le nom d'hôte contre la table ``Domain``, et doit donc s'exécuter
  avant tout ce qui lit ``request.get_host()`` ;
* ``SessionMiddleware`` charge la session depuis la base : le routage doit déjà
  être actif, sinon la session serait lue dans la base plateforme.

``TenantSessionGuardMiddleware`` est placé juste après
``AuthenticationMiddleware`` : la session est chargée, mais ``request.user``
reste paresseux — aucune requête SQL n'est gaspillée lorsque le garde rejette.
"""

import logging

from asgiref.local import Local
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import Http404
from django.utils.translation import gettext as _

from saas.context import activate, deactivate, get_current_key

logger = logging.getLogger(__name__)

#: Clé de session portant le sous-domaine de la société où la connexion a eu lieu.
TENANT_SESSION_KEY = "_blanco_tenant"

#: URLconf servie sur un hôte client : sans /admin/.
TENANT_URLCONF = "blanco.urls_tenant"

#: URLconf servie sur le domaine de la plateforme : site public, inscription
#: et administration. Aucune page métier de `core` n'y est montée, faute de
#: société à interroger.
PLATFORM_URLCONF = "blanco.urls_platform"

#: Préfixe de cache pour la résolution d'hôte. Le souligné initial le soustrait
#: au préfixage par société (voir ``saas.cache``) : cette clé est transverse.
CACHE_PREFIXE_HOTE = "_tenant_host:"
CACHE_DUREE_HOTE = 300

#: Sentinelle de cache : hôte inconnu. Évite de rejouer la requête SQL à chaque
#: appel d'un scanneur qui martèle des sous-domaines au hasard.
HOTE_INCONNU = "__inconnu__"

_requete = Local()


def requete_en_cours() -> bool:
    """Vrai si le fil courant sert une requête HTTP (utilisé par le mode strict)."""
    return bool(getattr(_requete, "active", False))


def _cle_cache(hote: str) -> str:
    return f"{CACHE_PREFIXE_HOTE}{hote}"


def oublier_hote(hostname: str) -> None:
    """
    Invalide la résolution en cache d'un nom d'hôte.

    À appeler après toute création, suppression ou changement d'état d'une
    entreprise — sans quoi un espace tout juste activé resterait injoignable
    jusqu'à cinq minutes.
    """
    if hostname:
        cache.delete(_cle_cache(hostname.strip().lower()))


def resoudre_entreprise(hote: str):
    """
    Retourne l'entreprise servie par ce nom d'hôte, ou ``None``.

    Mémoïsé : sans cela, chaque requête HTTP coûterait une requête SQL sur la
    base plateforme avant même d'avoir commencé à travailler.
    """
    from saas.models import Company

    cle = _cle_cache(hote)
    en_cache = cache.get(cle)
    if en_cache == HOTE_INCONNU:
        return None
    if en_cache is not None:
        entreprise = Company.objects.filter(pk=en_cache).first()
        if entreprise is not None:
            return entreprise
        cache.delete(cle)  # entrée périmée

    entreprise = (
        Company.objects.filter(
            domains__hostname=hote,
            domains__is_verified=True,
            delete_at__isnull=True,
        )
        .distinct()
        .first()
    )
    cache.set(cle, entreprise.pk if entreprise else HOTE_INCONNU, CACHE_DUREE_HOTE)
    return entreprise


class TenantMiddleware:
    """Résout l'entreprise à partir du nom d'hôte et l'active pour la requête."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _hotes_plateforme(self):
        from django.conf import settings

        domaine = getattr(settings, "BLANCO_PLATFORM_DOMAIN", "") or ""
        if not domaine:
            return set()
        return {domaine, f"www.{domaine}", f"admin.{domaine}"}

    def __call__(self, request):
        hote = request.get_host().split(":")[0].lower()

        _requete.active = True
        try:
            if hote in self._hotes_plateforme():
                # Site public, inscription, back-office : pas de société.
                request.tenant = None
                request.urlconf = PLATFORM_URLCONF
                return self.get_response(request)

            entreprise = resoudre_entreprise(hote)
            if entreprise is None:
                # Hôte inconnu : on refuse avant toute requête SQL métier, et
                # sans révéler si le sous-domaine existe mais est suspendu.
                raise Http404(_("Espace introuvable."))

            request.tenant = entreprise
            # Bascule sur l'URLconf des espaces clients : elle ne monte PAS
            # l'administration Django (voir blanco/urls_tenant.py).
            request.urlconf = TENANT_URLCONF

            if not entreprise.is_reachable:
                # L'espace existe mais ne peut pas servir (création en cours,
                # suspension). On n'active PAS sa base : la vue dédiée explique
                # la situation sans toucher aux données.
                request.tenant_indisponible = True
                return self.get_response(request)

            from saas.db import ensure_alias

            alias = ensure_alias(
                entreprise.db_alias,
                entreprise.db_name,
                **({"HOST": entreprise.db_host} if entreprise.db_host else {}),
            )
            activate(alias, entreprise.slug, entreprise)
            try:
                reponse = self.get_response(request)
            finally:
                # Impératif : gunicorn réutilise ses fils d'exécution. Sans
                # cette désactivation, la société resterait active pour la
                # requête suivante servie par ce même fil.
                deactivate()

            # Le contenu dépend du nom d'hôte : aucun cache intermédiaire ne
            # doit servir la page d'une société à une autre.
            reponse.headers.setdefault("Vary", "Host")
            return reponse
        finally:
            _requete.active = False


class TenantSessionGuardMiddleware:
    """
    Rejette une session estampillée d'une autre entreprise.

    Menace couverte
    ---------------
    Les cookies sont liés à l'hôte : un navigateur n'enverra jamais le cookie
    d'``acme`` à ``beta``. Un cookie **recopié à la main** (poste partagé, fuite
    de journaux) échoue déjà sur la comparaison ``_auth_user_hash`` de Django,
    puisque les empreintes de mot de passe sont salées aléatoirement.

    Il reste un cas où cette protection tombe : si une base société était
    **clonée** depuis une autre, les deux partageraient la même ligne ``staff``
    — même identifiant, même empreinte — et le rejeu fonctionnerait. Le
    provisionnement interdit formellement le clonage (toujours base vide +
    migrate + seed) ; ce garde est la seconde barrière, au cas où cette règle
    serait un jour violée.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        estampille = request.session.get(TENANT_SESSION_KEY)
        courante = get_current_key()
        if estampille is not None and estampille != courante:
            logger.warning(
                "Session estampillée « %s » présentée sur « %s » : session purgée.",
                estampille,
                courante,
            )
            request.session.flush()
            request.user = AnonymousUser()
        return self.get_response(request)
