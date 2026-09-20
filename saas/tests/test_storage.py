"""
Cloisonnement des fichiers déposés.

Exigence de compatibilité : les noms stockés en base ne changent pas. Seule la
racine du stockage suit la société active, ce qui évite toute migration de
données sur les installations existantes.
"""

import os
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import override_settings

from saas.context import tenant_context
from saas.storage import TenantFileSystemStorage, tenant_media_root
from saas.tests.base import ID_SOCIETE_A, ID_SOCIETE_B, IsolationTestCase, parametres_saas


@parametres_saas()
class StockageParSocieteTests(IsolationTestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp(prefix="blanco-medias-")
        self.addCleanup(shutil.rmtree, self.racine, ignore_errors=True)
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")

    def _stockage(self):
        return TenantFileSystemStorage()

    def test_la_racine_suit_la_societe_active(self):
        with override_settings(MEDIA_ROOT=self.racine):
            self.assertEqual(tenant_media_root(), self.racine)
            with tenant_context(self.societe_a):
                self.assertEqual(
                    tenant_media_root(),
                    os.path.join(self.racine, "tenants", "acme"),
                )
            with tenant_context(self.societe_b):
                self.assertEqual(
                    tenant_media_root(),
                    os.path.join(self.racine, "tenants", "beta"),
                )

    def test_un_fichier_depose_chez_a_est_absent_chez_b(self):
        with override_settings(MEDIA_ROOT=self.racine):
            stockage = self._stockage()

            with tenant_context(self.societe_a):
                nom = stockage.save("product/photo.jpg", ContentFile(b"image-a"))
                # Le NOM stocké en base reste relatif et inchangé : c'est ce qui
                # dispense de migrer les lignes existantes.
                self.assertEqual(nom, "product/photo.jpg")
                self.assertTrue(stockage.exists("product/photo.jpg"))

            with tenant_context(self.societe_b):
                self.assertFalse(stockage.exists("product/photo.jpg"))

    def test_deux_societes_peuvent_avoir_le_meme_nom_de_fichier(self):
        with override_settings(MEDIA_ROOT=self.racine):
            stockage = self._stockage()

            with tenant_context(self.societe_a):
                stockage.save("product/logo.png", ContentFile(b"aaa"))
            with tenant_context(self.societe_b):
                stockage.save("product/logo.png", ContentFile(b"bbb"))

            # Aucun suffixe de dé-collision : les deux vivent dans des dossiers
            # distincts et portent exactement le même nom relatif.
            with tenant_context(self.societe_a):
                with stockage.open("product/logo.png") as f:
                    self.assertEqual(f.read(), b"aaa")
            with tenant_context(self.societe_b):
                with stockage.open("product/logo.png") as f:
                    self.assertEqual(f.read(), b"bbb")

    def test_lurl_publique_reste_inchangee(self):
        # Le cloisonnement vient de l'hôte, pas du chemin : les gabarits
        # existants ({{ image.image.url }}) n'ont rien à changer.
        with override_settings(MEDIA_ROOT=self.racine, MEDIA_URL="/media/"):
            stockage = self._stockage()
            with tenant_context(self.societe_a):
                self.assertEqual(
                    stockage.url("product/photo.jpg"), "/media/product/photo.jpg"
                )

    def test_hors_societe_la_racine_reste_media_root(self):
        # Mode mono-client : rien ne doit changer.
        with override_settings(MEDIA_ROOT=self.racine):
            self.assertEqual(tenant_media_root(), self.racine)
