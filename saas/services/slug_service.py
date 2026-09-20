"""
Validation et disponibilité des sous-domaines.

Deux préoccupations distinctes, à ne pas confondre :

1. **La forme** — un sous-domaine doit être un libellé DNS valide, sans quoi le
   certificat et le routage échoueront plus tard, de façon obscure.
2. **La disponibilité** — libre, non réservé, et non déjà pris par un nom
   d'hôte existant (y compris le domaine propre d'un autre client).

Point de sécurité : la vérification de disponibilité est exposée en direct dans
le formulaire d'inscription, elle constitue donc un **oracle d'énumération**.
On ne répond jamais « ce sous-domaine existe déjà » — seulement
« indisponible » — et l'appel est limité en fréquence côté vue. Sans cela, on
offrirait la liste des clients de la plateforme à qui sait boucler.
"""

import re

from django.utils.translation import gettext as _

from saas.constants import SLUGS_RESERVES

#: Libellé DNS : commence par une lettre, finit par une lettre ou un chiffre,
#: tirets simples autorisés au milieu. 3 à 40 caractères.
MOTIF_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")

LONGUEUR_MIN = 3
LONGUEUR_MAX = 40


class SlugInvalide(ValueError):
    """Sous-domaine refusé. Le message est destiné à l'utilisateur."""


def normaliser(slug: str) -> str:
    return (slug or "").strip().lower()


def valider_forme(slug: str) -> str:
    """
    Contrôle la forme d'un sous-domaine et le retourne normalisé.

    Lève ``SlugInvalide`` avec un message explicite — l'utilisateur doit
    comprendre quoi corriger.
    """
    slug = normaliser(slug)

    if not slug:
        raise SlugInvalide(_("Indiquez un sous-domaine."))
    if len(slug) < LONGUEUR_MIN:
        raise SlugInvalide(_(
            "Le sous-domaine doit comporter au moins %(n)s caractères."
        ) % {"n": LONGUEUR_MIN})
    if len(slug) > LONGUEUR_MAX:
        raise SlugInvalide(_(
            "Le sous-domaine ne peut pas dépasser %(n)s caractères."
        ) % {"n": LONGUEUR_MAX})
    if "--" in slug:
        raise SlugInvalide(_("Le sous-domaine ne peut pas contenir deux tirets de suite."))
    if not MOTIF_SLUG.match(slug):
        raise SlugInvalide(_(
            "Le sous-domaine ne peut contenir que des lettres minuscules, des "
            "chiffres et des tirets, et doit commencer par une lettre."
        ))
    if slug.isdigit():
        raise SlugInvalide(_("Le sous-domaine ne peut pas être composé uniquement de chiffres."))
    return slug


def est_reserve(slug: str) -> bool:
    return normaliser(slug) in SLUGS_RESERVES


def est_disponible(slug: str, domaine_plateforme: str = "") -> bool:
    """
    Vrai si le sous-domaine est libre.

    Contrôle à la fois ``Company.slug`` et ``Domain.hostname`` : un domaine
    propre mal saisi pourrait déjà occuper le nom d'hôte correspondant.
    """
    from saas.models import Company, Domain

    slug = normaliser(slug)
    if not slug or est_reserve(slug):
        return False
    if Company.objects.filter(slug=slug).exists():
        return False
    if domaine_plateforme:
        if Domain.objects.filter(hostname=f"{slug}.{domaine_plateforme}").exists():
            return False
    return True


def valider_disponibilite(slug: str, domaine_plateforme: str = "") -> str:
    """
    Valide forme **et** disponibilité, et retourne le sous-domaine normalisé.

    Le message ne distingue pas « réservé » de « déjà pris » : les deux cas
    renvoient « indisponible », pour ne pas confirmer l'existence d'un client.
    """
    slug = valider_forme(slug)
    if not est_disponible(slug, domaine_plateforme):
        raise SlugInvalide(_("Ce sous-domaine n'est pas disponible. Essayez-en un autre."))
    return slug


def nom_de_base(slug: str, gabarit: str = "blanco_t_{slug}") -> str:
    """
    Nom de la base de données d'une entreprise.

    Les tirets sont convertis en soulignés : MySQL les accepterait entre
    accents graves, mais le nom finit interpolé dans du DDL et l'on veut
    pouvoir le valider par une expression régulière stricte.
    """
    return gabarit.format(slug=normaliser(slug).replace("-", "_"))
