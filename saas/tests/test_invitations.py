"""
Invitation d'employés.

Le point sensible : le jeton vit dans la base de la plateforme, l'utilisateur
dans celle de la société. C'est le couple (nom d'hôte, jeton) qui fait foi.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models.settings_models import AppModule
from saas.constants import ActionsAudit
from saas.context import tenant_context
from saas.models import (
    CompanyStatus,
    Invitation,
    InvitationStatus,
    JobKind,
    PlatformAuditLog,
    Plan,
    ProvisioningJob,
)
from saas.services import invitation_service
from saas.services.provisioning_service import provision
from saas.tests.base import (
    ID_SOCIETE_A,
    ID_SOCIETE_B,
    IsolationTestCase,
    parametres_saas,
    parametres_tenant,
)

User = get_user_model()


@parametres_saas()
class ServiceInvitationTests(IsolationTestCase):
    def setUp(self):
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )
        self.societe_a = self.creer_entreprise(ID_SOCIETE_A, "acme")
        self.societe_b = self.creer_entreprise(ID_SOCIETE_B, "beta")
        for societe in (self.societe_a, self.societe_b):
            with tenant_context(societe):
                AppModule.init_default_modules()

    def _inviter(self, societe=None, email="employe@acme.test", modules=None):
        return invitation_service.creer_invitation(
            societe or self.societe_a,
            email=email,
            module_codes=modules if modules is not None else ["sales", "products"],
        )

    def test_le_jeton_nest_jamais_stocke_en_clair(self):
        invitation, jeton = self._inviter()
        self.assertNotEqual(invitation.token_hash, jeton)
        self.assertEqual(len(invitation.token_hash), 64)
        self.assertTrue(invitation.correspond_au_jeton(jeton))

    def test_seuls_les_codes_de_modules_connus_sont_retenus(self):
        invitation, _ = self._inviter(modules=["sales", "inexistant", "accounting"])
        self.assertEqual(invitation.module_codes, ["sales", "accounting"])

    def test_le_couple_hote_jeton_fait_foi(self):
        _invitation, jeton = self._inviter(self.societe_a)
        # Le jeton d'acme, présenté sur l'espace de beta, ne vaut rien.
        self.assertIsNone(invitation_service.trouver_invitation(self.societe_b, jeton))
        self.assertIsNotNone(invitation_service.trouver_invitation(self.societe_a, jeton))

    def test_une_seule_invitation_en_cours_par_adresse(self):
        self._inviter()
        with self.assertRaises(invitation_service.InvitationInvalide):
            self._inviter()

    def test_on_ninvite_pas_un_membre_existant(self):
        with tenant_context(self.societe_a):
            User.objects.create_user(
                username="deja", email="employe@acme.test", password="MotDePasse!2026"
            )
        with self.assertRaises(invitation_service.InvitationInvalide):
            self._inviter()

    def test_le_quota_de_loffre_est_respecte(self):
        offre = Plan.objects.get(code="gratuit")
        offre.max_users = 1
        offre.save()
        self.societe_a.plan = offre
        self.societe_a.save()

        with tenant_context(self.societe_a):
            User.objects.create_user(username="seul", password="MotDePasse!2026")

        self.assertTrue(invitation_service.quota_atteint(self.societe_a))
        with self.assertRaises(invitation_service.InvitationInvalide):
            self._inviter()

    def test_une_offre_sans_limite_nempeche_rien(self):
        self.assertFalse(invitation_service.quota_atteint(self.societe_a))

    def test_lacceptation_cree_le_compte_dans_la_bonne_base(self):
        invitation, jeton = self._inviter()
        utilisateur = invitation_service.accepter(
            invitation, username="awa", mot_de_passe="MotDePasse!2026"
        )

        with tenant_context(self.societe_a):
            self.assertTrue(User.objects.filter(username="awa").exists())
        with tenant_context(self.societe_b):
            self.assertFalse(User.objects.filter(username="awa").exists())
        self.assertFalse(User.objects.using("default").filter(username="awa").exists())

    def test_lemploye_recoit_exactement_les_modules_prevus(self):
        invitation, _ = self._inviter(modules=["sales", "products"])
        utilisateur = invitation_service.accepter(
            invitation, username="awa", mot_de_passe="MotDePasse!2026"
        )
        with tenant_context(self.societe_a):
            utilisateur.refresh_from_db()
            codes = set(utilisateur.get_allowed_module_codes())
            self.assertEqual(codes, {"sales", "products"})
            # Et surtout : pas d'accès au reste.
            self.assertFalse(utilisateur.has_module_access("accounting"))
            self.assertFalse(utilisateur.is_superuser)
            self.assertFalse(utilisateur.is_staff)

    def test_linvitation_est_marquee_acceptee(self):
        invitation, _ = self._inviter()
        invitation_service.accepter(
            invitation, username="awa", mot_de_passe="MotDePasse!2026"
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, InvitationStatus.ACCEPTED)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertIsNotNone(invitation.accepted_user_id)

    def test_un_identifiant_deja_pris_est_refuse(self):
        with tenant_context(self.societe_a):
            User.objects.create_user(username="awa", password="MotDePasse!2026")
        invitation, _ = self._inviter()
        with self.assertRaises(invitation_service.InvitationInvalide):
            invitation_service.accepter(
                invitation, username="awa", mot_de_passe="MotDePasse!2026"
            )

    def test_deux_societes_peuvent_avoir_le_meme_identifiant(self):
        invitation_a, _ = self._inviter(self.societe_a, "a@acme.test")
        invitation_b, _ = self._inviter(self.societe_b, "b@beta.test")

        invitation_service.accepter(
            invitation_a, username="caisse", mot_de_passe="MotDePasse!2026"
        )
        # Ne doit pas lever : les identifiants sont uniques PAR base.
        invitation_service.accepter(
            invitation_b, username="caisse", mot_de_passe="MotDePasse!2026"
        )

    def test_une_invitation_revoquee_ne_vaut_plus_rien(self):
        invitation, jeton = self._inviter()
        invitation_service.revoquer(invitation)
        self.assertIsNone(invitation_service.trouver_invitation(self.societe_a, jeton))

    def test_le_renouvellement_invalide_lancien_jeton(self):
        invitation, ancien = self._inviter()
        nouveau = invitation_service.renouveler_jeton(invitation)

        self.assertIsNone(invitation_service.trouver_invitation(self.societe_a, ancien))
        self.assertIsNotNone(invitation_service.trouver_invitation(self.societe_a, nouveau))

    def test_les_actions_sont_consignees(self):
        invitation, _ = self._inviter()
        invitation_service.accepter(
            invitation, username="awa", mot_de_passe="MotDePasse!2026"
        )
        actions = set(PlatformAuditLog.objects.values_list("action", flat=True))
        self.assertIn(ActionsAudit.INVITATION_SENT, actions)
        self.assertIn(ActionsAudit.INVITATION_ACCEPTED, actions)


@parametres_tenant()
class VuesInvitationTests(IsolationTestCase):
    """Le parcours vu depuis le navigateur, sur l'espace de l'entreprise."""

    HOTE = "acme.blanco.test"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        Plan.objects.get_or_create(
            code="gratuit",
            defaults={"name": "Gratuit", "is_default": True, "is_active": True},
        )
        self.societe = self.creer_entreprise(
            ID_SOCIETE_A, "acme", statut=CompanyStatus.PENDING_VERIFICATION
        )
        self.societe.domains.update(is_verified=False)
        provision(self.societe)
        self.societe.refresh_from_db()

        with tenant_context(self.societe):
            self.responsable = User.objects.get(pk=self.societe.owner_user_id)
            self.responsable.set_password("MotDePasse!2026")
            self.responsable.save()

    def _connecter(self):
        self.client.post(
            "/login/",
            {"username": self.responsable.username, "password": "MotDePasse!2026"},
            HTTP_HOST=self.HOTE,
        )

    def test_la_page_des_invitations_est_accessible_au_responsable(self):
        self._connecter()
        reponse = self.client.get(reverse("invitations"), HTTP_HOST=self.HOTE)
        self.assertEqual(reponse.status_code, 200)

    def test_lenvoi_cree_linvitation_et_met_lemail_en_file(self):
        self._connecter()
        reponse = self.client.post(
            reverse("send_invitation"),
            {"email": "awa@acme.test", "modules": ["sales"], "role": "Caissière"},
            HTTP_HOST=self.HOTE,
        )
        self.assertEqual(reponse.status_code, 302)

        invitation = Invitation.objects.get(company=self.societe)
        self.assertEqual(invitation.email, "awa@acme.test")
        self.assertEqual(invitation.module_codes, ["sales"])
        self.assertEqual(ProvisioningJob.objects.filter(kind=JobKind.MAIL).count(), 1)

    def test_un_employe_accepte_et_se_retrouve_connecte(self):
        invitation, jeton = invitation_service.creer_invitation(
            self.societe, email="awa@acme.test", module_codes=["sales"]
        )
        reponse = self.client.post(
            reverse("accept_invitation", args=[jeton]),
            {
                "username": "awa",
                "password": "MotDePasse!2026",
                "password_confirmation": "MotDePasse!2026",
            },
            HTTP_HOST=self.HOTE,
        )
        self.assertEqual(reponse.status_code, 302)

        with tenant_context(self.societe):
            self.assertTrue(User.objects.filter(username="awa").exists())

    def test_un_jeton_invalide_affiche_le_message_unique(self):
        reponse = self.client.get(
            reverse("accept_invitation", args=["jeton-invente"]), HTTP_HOST=self.HOTE
        )
        self.assertEqual(reponse.status_code, 404)

    def test_un_utilisateur_sans_le_module_contacts_na_pas_acces(self):
        invitation, jeton = invitation_service.creer_invitation(
            self.societe, email="awa@acme.test", module_codes=["sales"]
        )
        invitation_service.accepter(
            invitation, username="awa", mot_de_passe="MotDePasse!2026"
        )
        self.client.post(
            "/login/",
            {"username": "awa", "password": "MotDePasse!2026"},
            HTTP_HOST=self.HOTE,
        )
        reponse = self.client.get(reverse("invitations"), HTTP_HOST=self.HOTE)
        self.assertEqual(reponse.status_code, 403)
