"""
Parcours d'inscription vu depuis le navigateur.

Ces tests suivent le chemin réel : formulaire → e-mail de vérification →
confirmation → page d'attente → espace utilisable.
"""

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from saas.models import (
    Company,
    CompanyStatus,
    JobKind,
    Plan,
    ProvisioningJob,
    SignupRequest,
)
from saas.tests.base import IsolationTestCase, parametres_saas

HOTE_PLATEFORME = "blanco.test"


@parametres_saas()
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SitePublicTests(IsolationTestCase):
    def setUp(self):
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )
        mail.outbox = []

    def _get(self, chemin):
        return self.client.get(chemin, HTTP_HOST=HOTE_PLATEFORME)

    def _post(self, chemin, donnees):
        return self.client.post(chemin, donnees, HTTP_HOST=HOTE_PLATEFORME)

    def _donnees_valides(self, **surcharges):
        donnees = {
            "nom": "ACME SARL",
            "slug": "acme",
            "email": "patron@acme.test",
            "contact_nom": "Awa Patron",
            "contact_telephone": "+237600000000",
            "mot_de_passe": "MotDePasse!2026",
            "mot_de_passe_confirmation": "MotDePasse!2026",
            "langue": "fr",
            "conditions": "on",
        }
        donnees.update(surcharges)
        return donnees

    # ── Pages ──────────────────────────────────────────────────────

    def test_laccueil_est_servi_sur_le_domaine_de_la_plateforme(self):
        reponse = self._get("/")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Blanco")

    def test_le_formulaire_dinscription_est_accessible(self):
        reponse = self._get(reverse("saas:inscription"))
        self.assertEqual(reponse.status_code, 200)

    def test_les_pages_metier_ne_sont_pas_servies_sur_la_plateforme(self):
        # `core` n'a aucune société à interroger sur le domaine racine.
        reponse = self._get("/login/")
        self.assertEqual(reponse.status_code, 404)

    def test_ladministration_est_montee_sur_la_plateforme(self):
        reponse = self._get("/admin/")
        self.assertIn(reponse.status_code, (200, 302))

    # ── Inscription ────────────────────────────────────────────────

    def test_une_inscription_valide_cree_lentreprise_et_envoie_lemail(self):
        reponse = self._post(reverse("saas:inscription"), self._donnees_valides())
        self.assertEqual(reponse.status_code, 302)

        entreprise = Company.objects.get(slug="acme")
        self.assertEqual(entreprise.status, CompanyStatus.PENDING_VERIFICATION)
        self.assertEqual(entreprise.contact_name, "Awa Patron")

        # L'e-mail passe par la file : rien n'est envoyé de façon synchrone.
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ProvisioningJob.objects.filter(kind=JobKind.MAIL).count(), 1)

    def test_un_sous_domaine_reserve_est_refuse(self):
        reponse = self._post(
            reverse("saas:inscription"), self._donnees_valides(slug="admin")
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Company.objects.filter(slug="admin").exists())

    def test_des_mots_de_passe_differents_sont_refuses(self):
        reponse = self._post(
            reverse("saas:inscription"),
            self._donnees_valides(mot_de_passe_confirmation="Autre!2026"),
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Company.objects.exists())

    def test_un_mot_de_passe_trop_faible_est_refuse(self):
        reponse = self._post(
            reverse("saas:inscription"),
            self._donnees_valides(mot_de_passe="1234", mot_de_passe_confirmation="1234"),
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Company.objects.exists())

    def test_les_conditions_doivent_etre_acceptees(self):
        donnees = self._donnees_valides()
        del donnees["conditions"]
        reponse = self._post(reverse("saas:inscription"), donnees)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Company.objects.exists())

    # ── Vérification de disponibilité ──────────────────────────────

    def test_la_verification_de_slug_repond_en_json(self):
        reponse = self._get(reverse("saas:verifier_slug") + "?slug=boutique-awa")
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.json()["disponible"])

    def test_un_slug_reserve_est_signale_indisponible(self):
        reponse = self._get(reverse("saas:verifier_slug") + "?slug=admin")
        self.assertFalse(reponse.json()["disponible"])

    def test_la_verification_noffre_pas_doracle(self):
        # « réservé » et « déjà pris » doivent donner le MÊME message, sans
        # quoi on confirmerait l'existence d'un client.
        self._post(reverse("saas:inscription"), self._donnees_valides())
        pris = self._get(reverse("saas:verifier_slug") + "?slug=acme").json()
        reserve = self._get(reverse("saas:verifier_slug") + "?slug=admin").json()
        self.assertEqual(pris["message"], reserve["message"])

    def test_la_verification_est_limitee_en_frequence(self):
        from saas.views.public_views import SLUG_MAX_APPELS

        chemin = reverse("saas:verifier_slug") + "?slug=quelque-chose"
        for _ in range(SLUG_MAX_APPELS):
            self._get(chemin)
        reponse = self._get(chemin)
        self.assertEqual(reponse.status_code, 429)

    # ── Confirmation ───────────────────────────────────────────────

    def _inscrire_et_recuperer_jeton(self):
        self._post(reverse("saas:inscription"), self._donnees_valides())
        job = ProvisioningJob.objects.get(kind=JobKind.MAIL)
        lien = job.payload["context"]["lien"]
        return Company.objects.get(slug="acme"), lien

    def test_le_lien_de_confirmation_lance_la_creation(self):
        entreprise, lien = self._inscrire_et_recuperer_jeton()
        chemin = lien.split(HOTE_PLATEFORME, 1)[1]

        reponse = self._get(chemin)
        self.assertEqual(reponse.status_code, 302)

        entreprise.refresh_from_db()
        self.assertEqual(entreprise.status, CompanyStatus.PROVISIONING)
        self.assertEqual(ProvisioningJob.objects.filter(kind=JobKind.PROVISION).count(), 1)

    def test_un_jeton_inconnu_affiche_le_meme_message_quun_jeton_expire(self):
        self._inscrire_et_recuperer_jeton()
        reponse = self._get(
            reverse("saas:confirmer", args=["acme", "jeton-invente"])
        )
        self.assertEqual(reponse.status_code, 404)
        # Message unique, qui ne distingue pas « inconnu » de « expiré ».
        self.assertContains(reponse, "plus valide", status_code=404)

    def test_la_page_dattente_indique_la_progression(self):
        entreprise, lien = self._inscrire_et_recuperer_jeton()
        self._get(lien.split(HOTE_PLATEFORME, 1)[1])

        reponse = self._get(reverse("saas:etat", args=["acme"]))
        donnees = reponse.json()
        self.assertEqual(donnees["status"], CompanyStatus.PROVISIONING)
        self.assertIn("progress", donnees)
        self.assertIn("label", donnees)

    def test_letat_dun_espace_inconnu_est_404(self):
        reponse = self._get(reverse("saas:etat", args=["inexistant"]))
        self.assertEqual(reponse.status_code, 404)

    def test_le_renvoi_de_verification_est_limite(self):
        from saas.views.public_views import RENVOI_MAX

        self._post(reverse("saas:inscription"), self._donnees_valides())
        demande = SignupRequest.objects.get()
        self.assertEqual(demande.send_count, 1)

        # Le délai minimal entre deux envois bloque un renvoi immédiat.
        self._post(reverse("saas:renvoyer_verification", args=["acme"]), {})
        demande.refresh_from_db()
        self.assertEqual(demande.send_count, 1)
        self.assertLessEqual(demande.send_count, RENVOI_MAX)
