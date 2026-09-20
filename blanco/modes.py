"""
Mode de déploiement de l'application.

Blanco se décline en deux modes, pilotés par la variable d'environnement
``BLANCO_MODE`` :

``standalone`` (défaut)
    Installation mono-client : une installation = une entreprise. C'est le
    mode historique — Docker sur le réseau local du commerce, ou exécutable
    Windows sur un poste. Découverte du serveur par QR code, une seule base,
    aucun routage. **Le comportement doit rester strictement identique à ce
    qu'il était avant l'introduction du multi-base.**

``saas``
    Plateforme hébergée multi-entreprises : une base MySQL par société,
    résolue à partir du nom d'hôte de la requête (sous-domaine ou domaine
    propre).

Ce module est volontairement sans dépendance : il est importé par
``blanco.settings`` avant toute initialisation de Django, et par ``core`` —
qui ne doit jamais importer l'application ``saas``.
"""

import os

STANDALONE = "standalone"
SAAS = "saas"

MODES = (STANDALONE, SAAS)


def get_mode() -> str:
    """
    Mode courant, lu dans l'environnement.

    On ne passe pas par ``django.conf.settings`` : ce module est utilisé
    pendant la construction même des settings. Toute valeur inconnue retombe
    sur ``standalone`` — en cas de faute de frappe, on dégrade vers le mode le
    plus restrictif plutôt que d'ouvrir une plateforme par accident.
    """
    mode = (os.environ.get("BLANCO_MODE") or STANDALONE).strip().lower()
    return mode if mode in MODES else STANDALONE


def is_saas() -> bool:
    """Vrai si l'application tourne en plateforme hébergée multi-entreprises."""
    try:
        from django.conf import settings

        # Une fois Django configuré, les settings font foi : les tests
        # peuvent ainsi basculer de mode avec @override_settings.
        if settings.configured:
            return bool(getattr(settings, "IS_SAAS", False))
    except Exception:  # pragma: no cover - avant/HORS configuration Django
        pass
    return get_mode() == SAAS


def is_standalone() -> bool:
    """Vrai si l'application tourne en installation mono-client."""
    return not is_saas()
