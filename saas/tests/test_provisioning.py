"""
Parcours d'inscription et provisionnement d'un espace.

Ces tests couvrent la promesse centrale du mode SaaS : une inscription en ligne
aboutit à un espace utilisable, isolé, avec ses données de référence.
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from core.models import Account, SystemSettings
from core.models.settings_models import AppModule
from saas.constants import ActionsAudit
from saas.context import tenant_context
from saas.models import (
    Company,
    CompanyStatus,
    JobKind,
    JobStatus,
    PlatformAuditLog,
    Plan,
    ProvisionStep,
    ProvisioningJob,
    SignupRequest,
)
from saas.services import signup_service, slug_service
from saas.services.provisioning_service import provision
from saas.tests.base import ID_SOCIETE_A, IsolationTestCase, parametres_saas

User = get_user_model()


@parametres_saas()
class ValidationDesSousDomainesTests(IsolationTestCase):
    def test_les_formes_invalides_sont_refusees(self):
        for mauvais in ("ab", "-acme", "acme-", "ACME!", "a--b", "123456", "x" * 41):
            with self.subTest(slug=mauvais):
                with self.assertRaises(slug_service.SlugInvalide):
                    slug_service.valider_forme(mauvais)

    def test_une_forme_valide_est_normalisee(self):
        self.assertEqual(slug_service.valider_forme("  ACME-Store "), "acme-store")

    def test_les_sous_domaines_reserves_sont_refuses(self):
        for reserve in ("www", "admin", "api", "mail", "billing", "support"):
            with self.subTest(slug=reserve):
                self.assertTrue(slug_service.est_reserve(reserve))
                self.assertFalse(slug_service.est_disponible(reserve))

    def test_un_sous_domaine_pris_devient_indisponible(self):
        self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.assertFalse(slug_service.est_disponible("acme"))
        self.assertTrue(slug_service.est_disponible("autre-boutique"))

    def test_le_message_ne_distingue_pas_reserve_et_deja_pris(self):
        # Pas d'oracle : on ne confirme jamais l'existence d'un client.
        self.creer_entreprise(ID_SOCIETE_A, "acme")
        messages = set()
        for slug in ("acme", "admin"):
            try:
                slug_service.valider_disponibilite(slug)
            except slug_service.SlugInvalide as exc:
                messages.add(str(exc))
        self.assertEqual(len(messages), 1)

    def test_le_nom_de_base_convertit_les_tirets(self):
        self.assertEqual(slug_service.nom_de_base("acme-store"), "blanco_t_acme_store")


@parametres_saas()
class InscriptionTests(IsolationTestCase):
    def setUp(self):
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )

    def _inscrire(self, slug="acme"):
        return signup_service.creer_inscription(
            nom="ACME SARL",
            slug=slug,
            email="patron@acme.test",
            mot_de_passe="MotDePasse!2026",
            domaine_plateforme="blanco.test",
        )

    def test_linscription_cree_une_entreprise_inactive(self):
        inscription, jeton = self._inscrire()
        entreprise = inscription.company

        self.assertEqual(entreprise.status, CompanyStatus.PENDING_VERIFICATION)
        self.assertFalse(entreprise.is_reachable)
        self.assertEqual(entreprise.db_name, "blanco_t_acme")
        self.assertIsNotNone(entreprise.plan)

    def test_le_sous_domaine_est_reserve_immediatement(self):
        self._inscrire()
        self.assertFalse(slug_service.est_disponible("acme"))

    def test_le_nom_dhote_est_cree_mais_non_verifie(self):
        inscription, _ = self._inscrire()
        domaine = inscription.company.primary_domain
        self.assertEqual(domaine.hostname, "acme.blanco.test")
        # Tant que l'espace n'existe pas, le nom d'hôte ne doit rien servir.
        self.assertFalse(domaine.is_verified)

    def test_le_mot_de_passe_nest_jamais_stocke_en_clair(self):
        inscription, _ = self._inscrire()
        self.assertNotIn("MotDePasse!2026", inscription.password_hash)
        self.assertTrue(inscription.password_hash.startswith(("pbkdf2", "argon2", "bcrypt")))

    def test_le_jeton_nest_jamais_stocke_en_clair(self):
        inscription, jeton = self._inscrire()
        self.assertNotEqual(inscription.token_hash, jeton)
        self.assertEqual(len(inscription.token_hash), 64)
        self.assertTrue(inscription.correspond_au_jeton(jeton))
        self.assertFalse(inscription.correspond_au_jeton("mauvais-jeton"))

    def test_un_sous_domaine_deja_pris_est_refuse(self):
        self._inscrire()
        with self.assertRaises(slug_service.SlugInvalide):
            self._inscrire()

    def test_laction_est_consignee(self):
        self._inscrire()
        self.assertTrue(
            PlatformAuditLog.objects.filter(action=ActionsAudit.SIGNUP_CREATED).exists()
        )

    def test_le_bon_couple_slug_jeton_retrouve_linscription(self):
        inscription, jeton = self._inscrire()
        self.assertEqual(signup_service.trouver_inscription("acme", jeton), inscription)

    def test_un_jeton_dune_autre_entreprise_ne_vaut_rien(self):
        _, jeton_a = self._inscrire("acme")
        self._inscrire("beta")
        # Le couple (sous-domaine, jeton) fait foi : un jeton présenté
        # ailleurs ne correspond à rien.
        self.assertIsNone(signup_service.trouver_inscription("beta", jeton_a))

    def test_un_jeton_expire_ne_vaut_rien(self):
        inscription, jeton = self._inscrire()
        inscription.expires_at = timezone.now() - timezone.timedelta(hours=1)
        inscription.save()
        self.assertIsNone(signup_service.trouver_inscription("acme", jeton))

    def test_la_verification_met_le_provisionnement_en_file(self):
        inscription, jeton = self._inscrire()
        signup_service.verifier_adresse(inscription)

        inscription.refresh_from_db()
        self.assertTrue(inscription.est_verifiee)
        self.assertEqual(inscription.company.status, CompanyStatus.PROVISIONING)
        self.assertEqual(
            ProvisioningJob.objects.filter(kind=JobKind.PROVISION).count(), 1
        )

    def test_rejouer_le_lien_ne_cree_pas_un_second_travail(self):
        inscription, jeton = self._inscrire()
        signup_service.verifier_adresse(inscription)
        signup_service.verifier_adresse(inscription)
        self.assertEqual(
            ProvisioningJob.objects.filter(kind=JobKind.PROVISION).count(), 1
        )

    def test_les_inscriptions_abandonnees_liberent_leur_sous_domaine(self):
        inscription, _ = self._inscrire()
        Company.objects.filter(pk=inscription.company.pk).update(
            create_at=timezone.now() - timezone.timedelta(days=30)
        )
        supprimees = signup_service.purger_inscriptions_abandonnees()
        self.assertEqual(supprimees, 1)
        self.assertTrue(slug_service.est_disponible("acme"))

    def test_une_inscription_verifiee_nest_jamais_purgee(self):
        inscription, _ = self._inscrire()
        signup_service.verifier_adresse(inscription)
        Company.objects.filter(pk=inscription.company.pk).update(
            create_at=timezone.now() - timezone.timedelta(days=30)
        )
        self.assertEqual(signup_service.purger_inscriptions_abandonnees(), 0)


@parametres_saas()
class ProvisionnementTests(IsolationTestCase):
    """
    De l'inscription à l'espace utilisable.

    Le provisionnement vise ici l'alias de test ``tenant_1001`` : l'entreprise
    reçoit donc la clé primaire correspondante, puisque l'alias en dérive.
    """

    def setUp(self):
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )
        self.entreprise = self.creer_entreprise(
            ID_SOCIETE_A, "acme", statut=CompanyStatus.PENDING_VERIFICATION
        )
        # Le nom d'hôte n'est vérifié qu'à la mise en service.
        self.entreprise.domains.update(is_verified=False)

    def test_le_provisionnement_active_lespace(self):
        provision(self.entreprise)
        self.entreprise.refresh_from_db()

        self.assertEqual(self.entreprise.status, CompanyStatus.ACTIVE)
        self.assertTrue(self.entreprise.is_reachable)
        self.assertIsNotNone(self.entreprise.provisioned_at)

    def test_lespace_recoit_ses_donnees_de_reference(self):
        provision(self.entreprise)
        with tenant_context(self.entreprise):
            # Les douze modules et le plan comptable OHADA, sans quoi la
            # navigation serait vide et les écritures échoueraient.
            self.assertEqual(AppModule.objects.count(), 12)
            self.assertGreater(Account.objects.count(), 0)
            self.assertTrue(Account.objects.filter(code="701").exists())
            self.assertTrue(Account.objects.filter(code="4431").exists())

    def test_le_plan_comptable_est_correctement_hierarchise(self):
        # Le rattachement au parent doit viser la base de la société, jamais
        # celle de la plateforme.
        provision(self.entreprise)
        with tenant_context(self.entreprise):
            compte = Account.objects.get(code="4431")
            self.assertIsNotNone(compte.parent)
            self.assertEqual(compte.parent.code, "443")

    def test_les_parametres_reprennent_le_nom_de_lentreprise(self):
        provision(self.entreprise)
        with tenant_context(self.entreprise):
            parametres = SystemSettings.get_settings()
            self.assertEqual(parametres.company_name, self.entreprise.name)
            self.assertEqual(parametres.company_email, self.entreprise.contact_email)

    def test_le_proprietaire_est_administrateur_mais_pas_staff(self):
        provision(self.entreprise)
        self.entreprise.refresh_from_db()

        with tenant_context(self.entreprise):
            proprietaire = User.objects.get(pk=self.entreprise.owner_user_id)
            # Superutilisateur DANS SA BASE : c'est ce qui lui donne ses douze
            # modules et la gestion de ses employés.
            self.assertTrue(proprietaire.is_superuser)
            # Mais jamais `is_staff` : l'administration Django lui reste
            # fermée même si l'URLconf était contournée.
            self.assertFalse(proprietaire.is_staff)
            self.assertTrue(proprietaire.is_active)

    def test_le_nom_dhote_est_mis_en_service(self):
        provision(self.entreprise)
        domaine = self.entreprise.primary_domain
        self.assertTrue(domaine.is_verified)
        self.assertIsNotNone(domaine.verified_at)

    def test_le_provisionnement_est_idempotent(self):
        provision(self.entreprise)
        self.entreprise.refresh_from_db()
        premiere_date = self.entreprise.provisioned_at

        provision(self.entreprise)  # ne doit rien casser
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.provisioned_at, premiere_date)
        with tenant_context(self.entreprise):
            self.assertEqual(AppModule.objects.count(), 12)
            self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)

    def test_laction_est_consignee(self):
        provision(self.entreprise)
        actions = set(
            PlatformAuditLog.objects.filter(company=self.entreprise)
            .values_list("action", flat=True)
        )
        self.assertIn(ActionsAudit.PROVISION_STARTED, actions)
        self.assertIn(ActionsAudit.PROVISION_SUCCEEDED, actions)

    def test_lespace_provisionne_reste_isole(self):
        provision(self.entreprise)
        with tenant_context(self.entreprise):
            User.objects.create_user(username="caisse", password="MotDePasse!2026")
        # Rien n'a fui vers la base de la plateforme.
        self.assertFalse(User.objects.using("default").filter(username="caisse").exists())


@parametres_saas()
class MoteurDeTravauxTests(IsolationTestCase):
    """La file de travaux doit réserver, exécuter et réessayer correctement."""

    def setUp(self):
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )
        self.entreprise = self.creer_entreprise(
            ID_SOCIETE_A, "acme", statut=CompanyStatus.PENDING_VERIFICATION
        )
        self.entreprise.domains.update(is_verified=False)

    def test_un_travail_de_provisionnement_aboutit(self):
        from saas.jobs.runner import boucle
        from saas.services.provisioning_service import mettre_en_file

        mettre_en_file(self.entreprise)
        traites = boucle(natures=[JobKind.PROVISION], once=True)

        self.assertEqual(traites, 1)
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.status, CompanyStatus.ACTIVE)

    def test_le_travail_progresse_jusqua_letape_finale(self):
        from saas.jobs.runner import boucle
        from saas.services.provisioning_service import mettre_en_file

        job = mettre_en_file(self.entreprise)
        boucle(natures=[JobKind.PROVISION], once=True)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.step, ProvisionStep.DONE)
        self.assertIsNotNone(job.finished_at)

    def test_une_seule_mise_en_file_par_entreprise(self):
        from saas.services.provisioning_service import mettre_en_file

        premier = mettre_en_file(self.entreprise)
        second = mettre_en_file(self.entreprise)
        self.assertEqual(premier.pk, second.pk)

    def test_un_travail_en_echec_est_remis_en_file(self):
        from saas.jobs.runner import executer, prendre_un_job

        job = ProvisioningJob.objects.create(
            company=None, kind=JobKind.PROVISION  # sans entreprise : échec assuré
        )
        reserve = prendre_un_job([JobKind.PROVISION])
        self.assertIsNotNone(reserve)

        abouti = executer(reserve)
        self.assertFalse(abouti)

        reserve.refresh_from_db()
        self.assertEqual(reserve.status, JobStatus.QUEUED)  # réessai prévu
        self.assertEqual(reserve.attempts, 1)
        self.assertIn("sans entreprise", reserve.last_error)
        self.assertGreater(reserve.run_after, timezone.now())

    def test_un_travail_abandonne_apres_trop_de_tentatives(self):
        from saas.jobs.runner import executer, prendre_un_job

        ProvisioningJob.objects.create(
            company=None, kind=JobKind.PROVISION, max_attempts=1
        )
        reserve = prendre_un_job([JobKind.PROVISION])
        executer(reserve)

        reserve.refresh_from_db()
        self.assertEqual(reserve.status, JobStatus.FAILED)

    def test_un_bail_expire_remet_le_travail_en_file(self):
        from saas.jobs.runner import liberer_baux_expires

        job = ProvisioningJob.objects.create(
            company=self.entreprise, kind=JobKind.PROVISION,
            status=JobStatus.RUNNING, step=ProvisionStep.MIGRATE,
            locked_by="machine-morte:1234",
            locked_at=timezone.now() - timezone.timedelta(hours=2),
        )
        liberes = liberer_baux_expires()

        self.assertEqual(liberes, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
        # Le point de reprise est CONSERVÉ : on ne rejoue pas ce qui a abouti.
        self.assertEqual(job.step, ProvisionStep.MIGRATE)
        self.assertEqual(job.locked_by, "")

    def test_un_travail_non_echu_nest_pas_reserve(self):
        from saas.jobs.runner import prendre_un_job

        ProvisioningJob.objects.create(
            company=self.entreprise, kind=JobKind.PROVISION,
            run_after=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertIsNone(prendre_un_job([JobKind.PROVISION]))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_lemail_de_bienvenue_part_apres_le_provisionnement(self):
        from saas.jobs.runner import boucle
        from saas.services.provisioning_service import mettre_en_file

        mail.outbox = []
        mettre_en_file(self.entreprise)
        boucle(natures=[JobKind.PROVISION], once=True)   # provisionne + met l'e-mail en file
        boucle(natures=[JobKind.MAIL], once=True)        # envoie l'e-mail

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn(self.entreprise.name, message.subject)
        self.assertIn(self.entreprise.contact_email, message.to)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_un_travail_demail_est_supprime_une_fois_envoye(self):
        from saas.jobs.runner import boucle
        from saas.services.mail_service import queue_mail

        mail.outbox = []
        job = queue_mail(
            "bienvenue", "quelquun@acme.test",
            {"entreprise": "ACME", "identifiant": "patron", "url": "https://acme.blanco.test"},
            company=self.entreprise,
        )
        boucle(natures=[JobKind.MAIL], once=True)

        # La charge utile peut contenir un jeton en clair : rien ne doit rester.
        self.assertFalse(ProvisioningJob.objects.filter(pk=job.pk).exists())
        self.assertEqual(len(mail.outbox), 1)
