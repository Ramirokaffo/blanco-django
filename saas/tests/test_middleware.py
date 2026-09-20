"""
Chemin de requête réel : résolution de l'hôte, fermeture de /admin/,
garde de session. Ces tests passent par le client de test HTTP.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory

from saas.context import tenant_context
from saas.middleware import (
    TENANT_SESSION_KEY,
    TenantSessionGuardMiddleware,
    oublier_hote,
    resoudre_entreprise,
)
from saas.models import CompanyStatus
from saas.tests.base import ID_SOCIETE_A, ID_SOCIETE_B, IsolationTestCase, parametres_saas

User = get_user_model()


@parametres_saas()
class ResolutionDeLHoteTests(IsolationTestCase):
    """L'entreprise servie est déduite du nom d'hôte, et de lui seul."""

    def setUp(self):
        cache.clear()
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")

    def test_un_hote_connu_resout_la_bonne_entreprise(self):
        self.assertEqual(resoudre_entreprise("acme.blanco.test"), self.societe_a)
        self.assertEqual(resoudre_entreprise("beta.blanco.test"), self.societe_b)

    def test_un_hote_inconnu_ne_resout_rien(self):
        self.assertIsNone(resoudre_entreprise("inexistant.blanco.test"))

    def test_un_hote_inconnu_renvoie_404(self):
        reponse = self.client.get("/login/", HTTP_HOST="inexistant.blanco.test")
        self.assertEqual(reponse.status_code, 404)

    def test_un_domaine_non_verifie_ne_resout_pas(self):
        # Un domaine propre tant qu'il n'est pas vérifié ne doit pas servir :
        # sinon n'importe qui pointerait un CNAME vers la plateforme.
        domaine = self.societe_a.domains.first()
        domaine.is_verified = False
        domaine.save()
        oublier_hote(domaine.hostname)
        self.assertIsNone(resoudre_entreprise(domaine.hostname))

    def test_une_entreprise_soft_supprimee_ne_resout_pas(self):
        from django.utils import timezone

        self.societe_a.delete_at = timezone.now()
        self.societe_a.save()
        oublier_hote("acme.blanco.test")
        self.assertIsNone(resoudre_entreprise("acme.blanco.test"))

    def test_loubli_du_cache_prend_effet_immediatement(self):
        self.assertIsNotNone(resoudre_entreprise("acme.blanco.test"))
        self.societe_a.domains.all().delete()
        oublier_hote("acme.blanco.test")
        self.assertIsNone(resoudre_entreprise("acme.blanco.test"))

    def test_lhote_de_la_plateforme_ne_porte_aucune_entreprise(self):
        # L'hôte plateforme est reconnu : il sert le site public, sans société
        # active et sans les pages métier de `core`.
        reponse = self.client.get("/", HTTP_HOST="blanco.test")
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.wsgi_request.tenant)


@parametres_saas()
class AdministrationFermeeCoteClientTests(IsolationTestCase):
    """
    /admin/ ne doit exister sur AUCUN hôte client.

    Sans ce verrou, le propriétaire d'un espace — superutilisateur dans sa
    propre base — lirait la liste de tous les clients de la plateforme, nom de
    base de données compris.
    """

    def setUp(self):
        cache.clear()
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")

    def test_admin_est_introuvable_sur_un_hote_client(self):
        reponse = self.client.get("/admin/", HTTP_HOST="acme.blanco.test")
        self.assertEqual(reponse.status_code, 404)

    def test_admin_du_plan_de_controle_est_introuvable_sur_un_hote_client(self):
        reponse = self.client.get("/admin/saas/company/", HTTP_HOST="acme.blanco.test")
        self.assertEqual(reponse.status_code, 404)

    def test_les_pages_metier_restent_servies_sur_un_hote_client(self):
        reponse = self.client.get("/login/", HTTP_HOST="acme.blanco.test")
        self.assertEqual(reponse.status_code, 200)


@parametres_saas()
class GardeDeSessionTests(IsolationTestCase):
    """Une session obtenue chez une société ne doit pas valoir chez une autre."""

    def setUp(self):
        cache.clear()
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")

        # Un utilisateur de MÊME identifiant et MÊME mot de passe dans les deux
        # bases : le pire cas, celui où seul le garde protège encore.
        for societe in (self.societe_a, self.societe_b):
            with tenant_context(societe):
                utilisateur = User.objects.create_user(
                    username="admin", password="MotDePasse!2026", is_active=True
                )
        self.utilisateur_factice = utilisateur

    def _se_connecter(self, hote):
        return self.client.post(
            "/login/",
            {"username": "admin", "password": "MotDePasse!2026"},
            HTTP_HOST=hote,
        )

    def test_la_session_est_estampillee_a_la_connexion(self):
        reponse = self._se_connecter("acme.blanco.test")
        self.assertEqual(reponse.status_code, 302)

        # La session vit dans la base de la société : il faut s'y placer pour
        # la relire. C'est en soi la preuve du cloisonnement.
        with tenant_context(self.societe_a):
            self.assertEqual(self.client.session.get(TENANT_SESSION_KEY), "acme")

    def test_la_session_nexiste_que_dans_la_base_de_sa_societe(self):
        self._se_connecter("acme.blanco.test")
        cle_session = self.client.cookies["sessionid"].value

        with tenant_context(self.societe_a):
            self.assertTrue(Session.objects.filter(session_key=cle_session).exists())
        with tenant_context(self.societe_b):
            self.assertFalse(Session.objects.filter(session_key=cle_session).exists())
        self.assertFalse(
            Session.objects.using("default").filter(session_key=cle_session).exists()
        )

    def test_un_cookie_dacme_rejoue_sur_beta_ne_connecte_personne(self):
        self._se_connecter("acme.blanco.test")

        # Le même cookie, présenté à l'espace d'une autre société.
        reponse = self.client.get("/", HTTP_HOST="beta.blanco.test")
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/login/", reponse["Location"])
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)

    def test_le_garde_purge_une_session_estampillee_dune_autre_societe(self):
        """
        Cas du clonage de base — la seule brèche que l'isolation par base ne
        couvre pas d'elle-même.

        Si une base société était clonée depuis une autre, les deux
        partageraient la même ligne ``staff`` (même identifiant, même empreinte
        de mot de passe) : la session serait alors valide des deux côtés. Le
        provisionnement interdit formellement le clonage ; ce garde est la
        seconde barrière. On l'éprouve donc directement.
        """
        requete = RequestFactory().get("/")
        requete.session = SessionStore()
        requete.session[TENANT_SESSION_KEY] = "acme"
        requete.session.save()
        requete.user = self.utilisateur_factice

        appele = {}

        def vue_suivante(req):
            appele["user"] = req.user
            return HttpResponse("ok")

        garde = TenantSessionGuardMiddleware(vue_suivante)
        with tenant_context(self.societe_b):  # présentée chez « beta »
            garde(requete)

        self.assertIsInstance(appele["user"], AnonymousUser)
        self.assertIsNone(requete.session.get(TENANT_SESSION_KEY))

    def test_le_garde_laisse_passer_une_session_de_la_bonne_societe(self):
        requete = RequestFactory().get("/")
        requete.session = SessionStore()
        requete.session[TENANT_SESSION_KEY] = "acme"
        requete.user = self.utilisateur_factice

        appele = {}

        def vue_suivante(req):
            appele["user"] = req.user
            return HttpResponse("ok")

        garde = TenantSessionGuardMiddleware(vue_suivante)
        with tenant_context(self.societe_a):
            garde(requete)

        self.assertIs(appele["user"], self.utilisateur_factice)
        self.assertEqual(requete.session.get(TENANT_SESSION_KEY), "acme")


@parametres_saas()
class EspaceIndisponibleTests(IsolationTestCase):
    """Un espace suspendu est résolu, mais sa base n'est jamais activée."""

    def setUp(self):
        cache.clear()

    def test_une_entreprise_suspendue_nactive_pas_sa_base(self):
        societe = self.creer_entreprise(
            ID_SOCIETE_A, "acme", statut=CompanyStatus.SUSPENDED
        )
        self.assertFalse(societe.is_reachable)

        reponse = self.client.get("/login/", HTTP_HOST="acme.blanco.test")
        # La requête aboutit (on pourra afficher un écran d'explication) mais
        # sans qu'aucune donnée de la société n'ait été touchée.
        self.assertTrue(getattr(reponse.wsgi_request, "tenant_indisponible", False))

    def test_une_entreprise_en_cours_de_creation_nest_pas_joignable(self):
        societe = self.creer_entreprise(
            ID_SOCIETE_B, "beta", statut=CompanyStatus.PROVISIONING
        )
        self.assertFalse(societe.is_reachable)
