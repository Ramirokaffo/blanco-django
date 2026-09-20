"""
Isolation entre entreprises : le cœur de la garantie du mode SaaS.

Chaque test ci-dessous correspond à un risque identifié lors de la conception.
Ils doivent rester verts : ce sont eux qui attestent qu'aucune donnée
comptable ne franchit la frontière entre deux sociétés.
"""

import threading

from django.core.cache import cache
from django.db.utils import ConnectionDoesNotExist
from django.test import SimpleTestCase

from core.models import Account, Product
from core.models.settings_models import AppModule
from saas.cache import tenant_key_func
from saas.context import (
    TenantNonActif,
    get_current_alias,
    get_current_key,
    platform_context,
    tenant_context,
)
from saas.db import (
    NomDeBaseInvalide,
    alias_for,
    ensure_alias,
    is_tenant_alias,
    valider_nom_de_base,
)
from saas.models import Company
from saas.tests.base import ALIAS_A, ALIAS_B, ID_SOCIETE_A, ID_SOCIETE_B, IsolationTestCase, parametres_saas


@parametres_saas()
class CloisonnementDesDonneesTests(IsolationTestCase):
    """Les données métier d'une société ne doivent jamais être visibles d'une autre."""

    def setUp(self):
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")

    def _creer_produit(self, code, nom):
        return Product.objects.create(
            code=code, name=nom, actual_price=1000, stock=5, stock_limit=1
        )

    def test_un_produit_cree_chez_a_est_invisible_chez_b(self):
        with tenant_context(self.societe_a):
            self._creer_produit("PRD-001", "Savon")
            self.assertEqual(Product.objects.filter(code="PRD-001").count(), 1)

        with tenant_context(self.societe_b):
            self.assertEqual(Product.objects.filter(code="PRD-001").count(), 0)

    def test_un_produit_de_societe_natteint_jamais_la_base_plateforme(self):
        with tenant_context(self.societe_a):
            self._creer_produit("PRD-002", "Sucre")
        self.assertEqual(
            Product.objects.using("default").filter(code="PRD-002").count(), 0
        )

    def test_le_meme_code_produit_coexiste_dans_deux_societes(self):
        # Product.code est unique=True : c'est précisément ce que l'isolation
        # par base rend possible, là où une colonne `company` aurait imposé de
        # réécrire la contrainte.
        with tenant_context(self.societe_a):
            self._creer_produit("REF-100", "Riz")
        with tenant_context(self.societe_b):
            self._creer_produit("REF-100", "Riz")  # ne doit pas lever

        with tenant_context(self.societe_a):
            self.assertEqual(Product.objects.get(code="REF-100").name, "Riz")
        with tenant_context(self.societe_b):
            self.assertEqual(Product.objects.get(code="REF-100").name, "Riz")

    def test_une_entreprise_reste_dans_la_base_plateforme(self):
        # Les modèles du plan de contrôle ne suivent JAMAIS la société active.
        with tenant_context(self.societe_a):
            Company.objects.create(
                pk=9999, name="Créée sous contexte", slug="sous-contexte",
                db_name="blanco_t_sous_contexte", contact_email="x@y.test",
            )
        self.assertTrue(Company.objects.using("default").filter(pk=9999).exists())

    def test_les_donnees_de_reference_sont_propres_a_chaque_base(self):
        # Modules et plan comptable sont semés par base : chacune a les siens.
        with tenant_context(self.societe_a):
            modules_a = AppModule.objects.count()
            comptes_a = Account.objects.count()
        with tenant_context(self.societe_b):
            modules_b = AppModule.objects.count()
            comptes_b = Account.objects.count()
        self.assertEqual(modules_a, modules_b)
        self.assertEqual(comptes_a, comptes_b)
        self.assertGreater(modules_a, 0)
        self.assertGreater(comptes_a, 0)


@parametres_saas()
class ContexteTenantTests(IsolationTestCase):
    """Le contexte doit être strictement symétrique : aucune fuite entre requêtes."""

    def setUp(self):
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")

    def test_le_contexte_est_efface_en_sortie(self):
        self.assertIsNone(get_current_alias())
        with tenant_context(self.societe_a):
            self.assertEqual(get_current_alias(), ALIAS_A)
        self.assertIsNone(get_current_alias())

    def test_le_contexte_est_restaure_meme_sur_exception(self):
        # Le cas qui, mal traité, laisse une société active sur un fil
        # réutilisé par gunicorn — et fait servir les données d'un autre client.
        with self.assertRaises(ValueError):
            with tenant_context(self.societe_a):
                raise ValueError("panne simulée")
        self.assertIsNone(get_current_alias())

    def test_les_contextes_imbriques_se_restaurent(self):
        with tenant_context(self.societe_a):
            with tenant_context(self.societe_b):
                self.assertEqual(get_current_alias(), ALIAS_B)
            self.assertEqual(get_current_alias(), ALIAS_A)
        self.assertIsNone(get_current_alias())

    def test_platform_context_suspend_puis_restaure(self):
        with tenant_context(self.societe_a):
            with platform_context():
                self.assertIsNone(get_current_alias())
            self.assertEqual(get_current_alias(), ALIAS_A)

    def test_la_cle_courante_est_le_sous_domaine(self):
        with tenant_context(self.societe_a):
            self.assertEqual(get_current_key(), "acme")

    def test_un_contexte_sans_societe_ni_alias_est_refuse(self):
        with self.assertRaises(ValueError):
            with tenant_context():
                pass


@parametres_saas(BLANCO_STRICT_TENANT=True)
class ModeStrictTests(IsolationTestCase):
    """Hors requête HTTP, le mode strict ne doit pas gêner l'exploitation."""

    def test_ecriture_hors_requete_reste_autorisee_sur_default(self):
        # Commandes d'administration, migrations, back-office : ils travaillent
        # légitimement sur `default` sans société active.
        Product.objects.create(
            code="ADMIN-1", name="Hors requête", actual_price=10, stock=1
        )
        self.assertTrue(Product.objects.filter(code="ADMIN-1").exists())

    def test_le_routeur_leve_si_une_requete_est_en_cours_sans_societe(self):
        from saas.middleware import _requete
        from saas.routers import TenantRouter

        _requete.active = True
        try:
            with self.assertRaises(TenantNonActif):
                TenantRouter().db_for_write(Product)
        finally:
            _requete.active = False


class EnregistrementDesAliasTests(SimpleTestCase):
    """``ensure_alias`` doit être idempotent, validant et sûr entre fils."""

    def test_alias_derive_de_la_cle_primaire(self):
        self.assertEqual(alias_for(42), "tenant_42")
        self.assertTrue(is_tenant_alias("tenant_42"))
        self.assertFalse(is_tenant_alias("default"))

    def test_un_nom_de_base_dangereux_est_refuse(self):
        # Le DDL ne se paramètre pas : le nom finit interpolé, il doit donc
        # être validé strictement.
        for nom in ("blanco; DROP DATABASE autre", "blanco-t-1", "", "a" * 65):
            with self.subTest(nom=nom):
                with self.assertRaises(NomDeBaseInvalide):
                    valider_nom_de_base(nom)

    def test_un_nom_de_base_licite_est_accepte(self):
        self.assertEqual(valider_nom_de_base("blanco_t_acme"), "blanco_t_acme")

    def test_enregistrement_concurrent_reste_coherent(self):
        # Le dictionnaire des bases est itéré à chaque requête par
        # close_old_connections : une mutation en place pourrait lever
        # « dictionary changed size during iteration ».
        from django.db import connections

        erreurs = []

        def enregistrer(indice):
            try:
                ensure_alias(f"tenant_concurrent_{indice}", f"blanco_c_{indice}")
            except Exception as exc:  # pragma: no cover
                erreurs.append(exc)

        fils = [threading.Thread(target=enregistrer, args=(i,)) for i in range(8)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()

        self.assertEqual(erreurs, [])
        for indice in range(8):
            self.assertIn(f"tenant_concurrent_{indice}", connections.settings)

        # Nettoyage : ces alias ne doivent pas fuiter vers les autres tests.
        from saas.db import forget_alias
        for indice in range(8):
            forget_alias(f"tenant_concurrent_{indice}")

    def test_un_alias_inconnu_reste_une_erreur_franche(self):
        from django.db import connections

        with self.assertRaises(ConnectionDoesNotExist):
            connections["tenant_jamais_enregistre"].cursor()


@parametres_saas()
class CloisonnementDuCacheTests(IsolationTestCase):
    """Deux sociétés ne doivent pas partager leurs compteurs de rate-limit."""

    def setUp(self):
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")
        cache.clear()

    def test_une_meme_cle_est_distincte_dans_deux_societes(self):
        # Scénario réel : l'« admin » de deux sociétés différentes.
        cle = "login-fail:user:1.2.3.4:admin"
        with tenant_context(self.societe_a):
            cache.set(cle, 5, 60)
        with tenant_context(self.societe_b):
            self.assertIsNone(cache.get(cle))
        with tenant_context(self.societe_a):
            self.assertEqual(cache.get(cle), 5)

    def test_les_cles_transverses_echappent_au_prefixage(self):
        # La résolution des noms d'hôte doit être partagée : c'est elle qui
        # sert à TROUVER la société.
        with tenant_context(self.societe_a):
            self.assertEqual(
                tenant_key_func("_tenant_host:acme.blanco.test", "blanco", 1),
                "blanco:1:_tenant_host:acme.blanco.test",
            )

    def test_hors_societe_les_cles_portent_la_marque_plateforme(self):
        self.assertEqual(tenant_key_func("x", "blanco", 1), "blanco:1:-:x")
