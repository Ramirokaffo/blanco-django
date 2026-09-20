"""
Offres commerciales.

La facturation n'est pas au programme de la première version. On installe
néanmoins ``Plan`` dès maintenant, pour une raison précise : **le point de
coupure**. Toute la difficulté d'un système d'abonnement n'est pas de compter
l'argent, c'est de couper proprement l'accès d'un client qui ne paie plus, sans
perdre ses données ni casser son espace. Ce mécanisme existe déjà —
``Company.status = SUSPENDED`` — et il est éprouvé par les tests.

Le jour où la facturation arrivera, elle n'aura qu'à basculer ce statut.

On s'abstient en revanche de créer ``Subscription`` et ``Invoice`` : ajouter
une table plus tard est une migration purement additive, et la remplir
rétroactivement est trivial (``Company.plan`` et ``provisioned_at`` suffisent).
Créer aujourd'hui des tables vides qu'on ne saurait pas remplir correctement
coûterait plus cher que de les ajouter au bon moment.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _, gettext_noop


class Plan(models.Model):
    """Offre à laquelle une entreprise est rattachée."""

    code = models.SlugField(max_length=30, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=100, verbose_name=_("Nom"))
    description = models.TextField(blank=True, default="", verbose_name=_("Description"))

    # ``None`` = illimité. Un 0 signifierait « aucun », ce qui n'a pas de sens ici.
    max_users = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Nombre d'utilisateurs maximum"),
        help_text=_("Vide = illimité."),
    )
    max_products = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Nombre de produits maximum"),
        help_text=_("Vide = illimité."),
    )

    price_xaf = models.PositiveIntegerField(
        default=0, verbose_name=_("Prix mensuel (FCFA)")
    )
    trial_days = models.PositiveIntegerField(
        default=0, verbose_name=_("Durée de l'essai (jours)")
    )

    is_active = models.BooleanField(default=True, verbose_name=_("Offre proposée"))
    is_default = models.BooleanField(
        default=False, verbose_name=_("Offre par défaut"),
        help_text=_("Attribuée aux nouvelles inscriptions."),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Ordre d'affichage"))

    class Meta:
        db_table = "saas_plan"
        verbose_name = _("Offre")
        verbose_name_plural = _("Offres")
        ordering = ["order", "price_xaf"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="une_seule_offre_par_defaut",
            )
        ]

    def __str__(self):
        from django.utils.translation import gettext

        return gettext(self.name)

    @property
    def users_illimites(self) -> bool:
        return self.max_users is None

    @classmethod
    def get_default(cls):
        """Offre attribuée aux nouvelles inscriptions."""
        return cls.objects.filter(is_default=True, is_active=True).first()


#: Offre unique de départ : illimitée et gratuite. Les libellés passent par
#: gettext_noop pour être extraits, et sont traduits à l'affichage — même
#: convention que DEFAULT_MODULES et DEFAULT_ACCOUNTS dans `core`.
DEFAULT_PLANS = [
    {
        "code": "gratuit",
        "name": gettext_noop("Gratuit"),
        "description": gettext_noop("Accès complet, sans limite d'utilisateurs."),
        "max_users": None,
        "max_products": None,
        "price_xaf": 0,
        "trial_days": 0,
        "is_default": True,
        "order": 1,
    },
]


def init_default_plans(using=None) -> int:
    """Crée les offres par défaut manquantes. Idempotent."""
    crees = 0
    for donnees in DEFAULT_PLANS:
        code = donnees["code"]
        _plan, cree = Plan.objects.db_manager(using).get_or_create(
            code=code,
            defaults={cle: valeur for cle, valeur in donnees.items() if cle != "code"},
        )
        if cree:
            crees += 1
    return crees
