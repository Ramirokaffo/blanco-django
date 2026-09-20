"""
Enregistrement à chaud des alias de bases de données des entreprises clientes.

Pourquoi ce module existe
-------------------------
Django lit ``settings.DATABASES`` **une seule fois**, via la ``cached_property``
``BaseConnectionHandler.settings`` (django/utils/connection.py). Une entreprise
créée après le démarrage du serveur n'a donc pas d'alias : il faut l'ajouter au
gestionnaire de connexions en cours de route. Deux pièges, tous deux vérifiés
dans les sources de Django 4.2 :

1. **Les valeurs par défaut ne sont appliquées qu'une fois.**
   ``ConnectionHandler.configure_settings`` (django/db/utils.py) complète chaque
   entrée avec ``ATOMIC_REQUESTS``, ``AUTOCOMMIT``, ``ENGINE``, ``CONN_MAX_AGE``,
   ``CONN_HEALTH_CHECKS``, ``OPTIONS``, ``TIME_ZONE``, ``NAME``/``USER``/
   ``PASSWORD``/``HOST``/``PORT`` et le bloc ``TEST``. Un alias inséré après
   coup ne passe pas par cette normalisation : il manquerait des clés et
   ``create_connection()`` lèverait un ``KeyError``.
   → On part donc d'une **copie de l'entrée ``default``**, déjà normalisée, et
   on n'écrase que ce qui distingue la base de l'entreprise.

2. **Le dictionnaire est itéré pendant les requêtes.**
   ``close_old_connections`` est branché sur ``request_started`` et
   ``request_finished`` (django/db/__init__.py) et parcourt ``connections.all()``,
   qui itère ``self.settings``. Muter ce dictionnaire en place depuis un autre
   fil d'exécution peut lever
   ``RuntimeError: dictionary changed size during iteration``.
   → On procède par **copie puis remplacement** : la réaffectation d'un nom est
   atomique sous le GIL, et une itération déjà engagée termine sur l'ancien
   dictionnaire sans incident.

Budget de connexions
--------------------
``ConnectionHandler.thread_critical`` vaut ``True`` : les connexions sont par
fil d'exécution. Le pire cas est
``workers × threads × sociétés servies par ce fil``. Avec ``CONN_MAX_AGE = 0``
(défaut retenu en mode SaaS), Django ferme la connexion en fin de requête et le
total reste borné. Ne relever cette valeur qu'après avoir mesuré le coût réel
de l'établissement de connexion, et en remontant ``max_connections`` côté MySQL.
"""

import copy
import re
import threading

from django.conf import settings
from django.db import connections

#: Préfixe des alias gérés par ce module. Sert aussi à les reconnaître.
TENANT_ALIAS_PREFIX = "tenant_"

#: Noms de bases acceptés. Le DDL ne se paramètre pas (``CREATE DATABASE %s``
#: est impossible) : le nom est donc interpolé, et doit être validé strictement.
NOM_BASE_VALIDE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

_verrou = threading.RLock()


class NomDeBaseInvalide(ValueError):
    """Nom de base refusé : il finirait interpolé dans une requête DDL."""


def valider_nom_de_base(db_name: str) -> str:
    """Valide un nom de base destiné à être interpolé dans du DDL."""
    if not db_name or not NOM_BASE_VALIDE.match(db_name):
        raise NomDeBaseInvalide(
            "Nom de base invalide : %r (attendu : lettres, chiffres et "
            "soulignés, 64 caractères au plus)." % (db_name,)
        )
    return db_name


def alias_for(company_id) -> str:
    """Alias Django de la base d'une entreprise : ``tenant_42``."""
    return f"{TENANT_ALIAS_PREFIX}{company_id}"


def is_tenant_alias(alias: str) -> bool:
    """Vrai si l'alias désigne la base d'une entreprise cliente."""
    return bool(alias) and alias.startswith(TENANT_ALIAS_PREFIX)


def alias_enregistre(alias: str) -> bool:
    """Vrai si l'alias est déjà connu du gestionnaire de connexions."""
    return alias in connections.settings


def ensure_alias(alias: str, db_name: str, **surcharges) -> str:
    """
    Déclare ``alias`` dans le gestionnaire de connexions s'il n'y est pas déjà.

    Idempotent et sûr entre fils d'exécution. À rejouer dans chaque processus
    de travail — gunicorn ne partage rien entre ses workers : d'où l'appel
    paresseux depuis le middleware plutôt qu'un préchargement au démarrage.

    ``surcharges`` permet de viser un autre serveur ou d'autres identifiants
    (``HOST``, ``USER``, ``PASSWORD``) : l'alias est ainsi une indirection
    suffisante pour répartir les sociétés sur plusieurs serveurs MySQL, sans
    aucun changement de schéma.
    """
    valider_nom_de_base(db_name)

    # L'accès à `connections.settings` déclenche la normalisation initiale.
    configuration = connections.settings
    if alias in configuration:
        return alias

    with _verrou:
        configuration = connections.settings
        if alias in configuration:  # double contrôle sous verrou
            return alias

        base = configuration["default"]
        entree = copy.deepcopy(base)
        entree["NAME"] = db_name
        entree["CONN_MAX_AGE"] = getattr(settings, "TENANT_CONN_MAX_AGE", 0)
        # Jamais de transaction implicite par requête sur une base société :
        # les services gèrent eux-mêmes leurs `transaction.atomic()`.
        entree["ATOMIC_REQUESTS"] = False
        entree["TEST"] = {
            **copy.deepcopy(base.get("TEST") or {}),
            "NAME": f"test_{db_name}",
        }
        entree.update(surcharges)

        # Copie puis remplacement (cf. piège n° 2 de l'en-tête).
        nouvelle_configuration = {**configuration, alias: entree}
        connections.__dict__["settings"] = nouvelle_configuration
        connections._settings = nouvelle_configuration
        settings.DATABASES = nouvelle_configuration
        return alias


def forget_alias(alias: str) -> None:
    """
    Retire un alias du gestionnaire (après suppression d'une entreprise).

    Ferme d'abord la connexion du fil courant s'il en avait ouvert une.
    """
    if not is_tenant_alias(alias):
        raise ValueError("forget_alias ne s'applique qu'aux alias de société.")

    with _verrou:
        configuration = connections.settings
        if alias not in configuration:
            return
        try:
            connections[alias].close()
        except Exception:  # pragma: no cover - connexion jamais ouverte
            pass
        nouvelle_configuration = {
            cle: valeur for cle, valeur in configuration.items() if cle != alias
        }
        connections.__dict__["settings"] = nouvelle_configuration
        connections._settings = nouvelle_configuration
        settings.DATABASES = nouvelle_configuration


def close_tenant_connections(**kwargs) -> None:
    """
    Ferme les connexions aux bases sociétés ouvertes par le fil courant.

    Sans objet tant que ``TENANT_CONN_MAX_AGE`` vaut 0 (Django ferme alors
    lui-même sur ``request_finished``). À brancher sur ce signal si l'on active
    des connexions persistantes, pour éviter qu'un fil ne conserve une
    connexion par société qu'il a servie.
    """
    for connexion in connections.all(initialized_only=True):
        if is_tenant_alias(connexion.alias):
            connexion.close()
