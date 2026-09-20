"""
Cloisonnement du cache par entreprise.

Le rate-limit de connexion (``core/views.py``) et les throttles DRF utilisent
le cache avec des clés du type ``login-fail:user:<ip>:<identifiant>``. Avec un
Redis partagé entre sociétés, l'« admin » de l'une et l'« admin » de l'autre
se partageraient le même compteur : un attaquant bloquerait les connexions
d'un concurrent, discrètement.

On préfixe donc toutes les clés par la société active, via ``KEY_FUNCTION``.
L'intérêt de ce point d'accroche : ni ``core/views.py`` ni les throttles DRF
n'ont besoin d'être modifiés.

Les clés volontairement transverses commencent par ``_`` et échappent au
préfixage — c'est le cas de la résolution des noms d'hôte, qui doit
précisément être partagée puisqu'elle sert à trouver la société.
"""

from saas.context import get_current_key

#: Marqueur des clés transverses, non rattachées à une société.
PREFIXE_TRANSVERSE = "_"

#: Valeur utilisée hors contexte société (plateforme, commandes, migrations).
CLE_PLATEFORME = "-"


def tenant_key_func(key, key_prefix, version):
    """``KEY_FUNCTION`` du cache : préfixe chaque clé par la société active."""
    if key.startswith(PREFIXE_TRANSVERSE):
        return "%s:%s:%s" % (key_prefix, version, key)
    return "%s:%s:%s:%s" % (key_prefix, version, get_current_key() or CLE_PLATEFORME, key)
