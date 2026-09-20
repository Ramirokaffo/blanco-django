"""
Routeur de bases de données.

Règle unique et lisible :

* les modèles du **plan de contrôle** (application ``saas``) vivent toujours
  dans ``default`` — c'est là que se trouvent la liste des entreprises, les
  invitations et le journal d'audit ;
* **tout le reste** (``core``, mais aussi ``auth``, ``sessions``, ``admin``,
  ``contenttypes``, ``authtoken``) va dans la base de la société active, ou
  dans ``default`` si aucune société n'est active.

Conséquence voulue : ``core`` n'a pas une ligne à changer. Aucun ``using()``,
aucun ``db_manager()``, aucun SQL brut n'existe dans l'application métier — le
routeur contrôle donc la totalité des accès.

``default`` porte le schéma complet
-----------------------------------
On laisse migrer *toutes* les applications dans ``default``, exactement comme
en mode mono-client. Cela coûte quelques tables inutilisées dans la base
plateforme et rapporte beaucoup : aucune divergence entre les deux modes, un
``manage.py migrate`` sans option qui reste correct, la suite de tests
existante intacte, et un back-office qui dispose de ``core.CustomUser`` —
indispensable puisque ``AUTH_USER_MODEL`` est global à Django.

Mode strict
-----------
``BLANCO_STRICT_TENANT`` (défaut : actif en mode SaaS) fait échouer une
lecture ou une écriture métier tentée pendant une requête HTTP sans société
active, au lieu de la laisser silencieusement atterrir dans la base
plateforme. Échouer bruyamment vaut mieux qu'une fuite d'écriture.
"""

from django.conf import settings

from saas.context import TenantNonActif, get_current_alias

#: Applications du plan de contrôle : jamais routées, toujours sur ``default``.
CONTROL_PLANE_APPS = {"saas"}

#: Applications dont les données appartiennent à une société.
#: Les applications techniques de Django (auth, sessions, admin, contenttypes)
#: suivent ``core`` : les comptes et les sessions d'une société vivent chez
#: elle, ce qui rend un cookie ou un jeton d'une société inopérant chez une
#: autre — l'isolation ne repose alors pas sur une simple vérification.
TENANT_APPS = {
    "core",
    "auth",
    "sessions",
    "admin",
    "contenttypes",
    "authtoken",
}


class TenantRouter:
    """Aiguille chaque requête ORM vers la base de la société active."""

    def _base(self, app_label, hints=None, ecriture=False):
        if app_label in CONTROL_PLANE_APPS:
            return "default"

        # La société active fait foi pendant une requête.
        alias = get_current_alias()
        if alias:
            return alias

        # Hors contexte, Django transmet l'objet lié en indice lorsqu'il
        # affecte une clé étrangère (related_descriptors.ForwardManyToOneDescriptor)
        # ou qu'il suit une relation. Si cet objet est déjà rattaché à une
        # base, la relation doit rester dans CETTE base : c'est le cas d'un
        # `migrate --database=<alias>`, dont le seed rattache un compte
        # comptable à son parent sans qu'aucune société ne soit active.
        instance = (hints or {}).get("instance")
        base_de_linstance = getattr(getattr(instance, "_state", None), "db", None)
        if base_de_linstance:
            return base_de_linstance

        if ecriture and app_label in TENANT_APPS and self._mode_strict():
            raise TenantNonActif(
                "Écriture sur « %s » sans société active. Enveloppez l'appel "
                "dans saas.context.tenant_context(company)." % app_label
            )
        return "default"

    @staticmethod
    def _mode_strict() -> bool:
        """
        Le mode strict ne s'applique qu'au service d'une requête HTTP.

        Les commandes d'administration, les migrations et le back-office
        travaillent légitimement sur ``default`` sans société active.
        """
        if not getattr(settings, "BLANCO_STRICT_TENANT", False):
            return False
        from saas.middleware import requete_en_cours

        return requete_en_cours()

    def db_for_read(self, model, **hints):
        return self._base(model._meta.app_label, hints)

    def db_for_write(self, model, **hints):
        return self._base(model._meta.app_label, hints, ecriture=True)

    def allow_relation(self, obj1, obj2, **hints):
        """
        Une relation n'a de sens qu'entre deux objets de la même base.

        Tout le schéma d'une société tient dans une seule base : une relation
        inter-bases traduirait une erreur de contexte, jamais un cas légitime.
        On répond ``None`` (décision de Django) tant qu'un des objets n'est pas
        rattaché à une base, pour ne pas gêner les objets non sauvegardés.
        """
        base1 = obj1._state.db
        base2 = obj2._state.db
        if base1 is None or base2 is None:
            return None
        return base1 == base2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in CONTROL_PLANE_APPS:
            # Le plan de contrôle n'existe que dans la base plateforme.
            return db == "default"
        # Partout ailleurs : schéma complet dans `default` comme dans chaque
        # base société (voir l'en-tête du module).
        return True
