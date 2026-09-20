"""
Entreprise active du contexte d'exécution courant.

Le routeur de bases (``saas.routers``) n'a aucun accès à la requête HTTP : il
lit ici la société à viser. Ce module est donc le seul point qui sait « pour
qui » travaille le fil d'exécution en cours.

Choix de la primitive
---------------------
``asgiref.local.Local`` — celle que Django emploie lui-même pour ses connexions.
Sous le capot, ce sont des ``contextvars`` protégés par un verrou :

* un ``threading.local`` nu **fuiterait entre requêtes** : gunicorn réutilise
  ses fils, une société resterait active pour la requête suivante ;
* un ``contextvars.ContextVar`` nu n'est pas protégé en écriture concurrente.

Règle d'or : toute activation doit être annulée dans un ``finally``. Le
middleware et ``tenant_context`` s'en chargent ; n'appelez ``activate()``
directement que si vous garantissez la symétrie.
"""

from contextlib import contextmanager

from asgiref.local import Local

from saas.db import alias_for, ensure_alias

_etat = Local()


class TenantNonActif(RuntimeError):
    """
    Aucune société active alors que le mode strict l'exige.

    Levée plutôt que de laisser une écriture métier atterrir silencieusement
    dans la base de la plateforme.
    """


def get_current_alias():
    """Alias de base de la société active, ou ``None`` hors contexte société."""
    return getattr(_etat, "alias", None)


def get_current_key():
    """
    Clé courte de la société active (son sous-domaine), ou ``None``.

    Sert à préfixer les clés de cache et la racine des médias : on veut un
    identifiant lisible et stable, pas un numéro de base.
    """
    return getattr(_etat, "key", None)


def get_current_company():
    """Instance ``Company`` active, si l'activation en a fourni une."""
    return getattr(_etat, "company", None)


def activate(alias: str, key: str, company=None) -> None:
    """Active une société pour le fil/contexte courant."""
    _etat.alias = alias
    _etat.key = key
    _etat.company = company


def deactivate() -> None:
    """Efface la société active. À appeler systématiquement dans un ``finally``."""
    for attribut in ("alias", "key", "company"):
        try:
            delattr(_etat, attribut)
        except AttributeError:
            pass


@contextmanager
def tenant_context(company=None, *, alias=None, key=None):
    """
    Active une société hors du cycle requête/réponse.

        with tenant_context(company):
            Product.objects.count()   # lit la base de cette société

    ``company`` est une instance ``saas.Company`` (elle fournit ``id``, ``slug``
    et ``db_name``) ; ``alias``/``key`` permettent de s'en passer, notamment
    dans les tests d'isolation.

    Réentrant : le contexte précédent est restauré à la sortie, y compris sur
    exception. Des appels imbriqués sont donc sûrs.
    """
    if company is not None:
        alias = ensure_alias(alias_for(company.id), company.db_name)
        key = company.slug
    elif alias is None:
        raise ValueError("tenant_context exige une société ou un alias explicite.")

    precedent = (get_current_alias(), get_current_key(), get_current_company())
    activate(alias, key, company)
    try:
        yield alias
    finally:
        if precedent[0] is None:
            deactivate()
        else:
            activate(*precedent)


@contextmanager
def platform_context():
    """
    Suspend temporairement la société active (retour à la base plateforme).

    Utile lorsqu'un traitement lancé dans le contexte d'une société doit
    écrire dans le plan de contrôle — par exemple marquer une invitation
    acceptée.
    """
    precedent = (get_current_alias(), get_current_key(), get_current_company())
    deactivate()
    try:
        yield
    finally:
        if precedent[0] is not None:
            activate(*precedent)
