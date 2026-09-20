"""
Garde-fou du dernier administrateur.

Un responsable qui se retire ses propres droits s'enferme dehors : plus
personne ne peut gérer les comptes ni les paramètres, et seule une
intervention directe sur la base rouvre l'accès. En hébergement mutualisé,
cela signifie un ticket de support et un accès aux données du client.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.services.media import current_media_root
from core.services.staff_service import StaffService

User = get_user_model()


class DernierAdministrateurTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", password="MotDePasse!2026"
        )

    def test_le_seul_administrateur_est_protege(self):
        self.assertTrue(StaffService.is_last_active_superuser(self.admin))
        with self.assertRaises(ValueError):
            StaffService.ensure_not_last_superuser(self.admin)

    def test_avec_un_second_administrateur_le_retrait_est_permis(self):
        User.objects.create_superuser(username="admin2", password="MotDePasse!2026")
        self.assertFalse(StaffService.is_last_active_superuser(self.admin))
        StaffService.ensure_not_last_superuser(self.admin)  # ne doit pas lever

    def test_un_second_administrateur_inactif_ne_compte_pas(self):
        User.objects.create_superuser(
            username="admin2", password="MotDePasse!2026", is_active=False
        )
        self.assertTrue(StaffService.is_last_active_superuser(self.admin))

    def test_un_second_administrateur_supprime_ne_compte_pas(self):
        autre = User.objects.create_superuser(
            username="admin2", password="MotDePasse!2026"
        )
        autre.delete_at = timezone.now()
        autre.save()
        self.assertTrue(StaffService.is_last_active_superuser(self.admin))

    def test_un_utilisateur_ordinaire_nest_pas_concerne(self):
        simple = User.objects.create_user(
            username="caisse", password="MotDePasse!2026"
        )
        self.assertFalse(StaffService.is_last_active_superuser(simple))
        StaffService.ensure_not_last_superuser(simple)  # ne doit pas lever

    def test_le_comptage_exclut_bien_lutilisateur_vise(self):
        self.assertEqual(
            StaffService.count_active_superusers(exclude_pk=self.admin.pk), 0
        )
        self.assertEqual(StaffService.count_active_superusers(), 1)


class RacineDesMediasTests(TestCase):
    """En mono-client, la racine des médias ne doit pas bouger d'un pouce."""

    def test_en_mono_client_la_racine_est_media_root(self):
        from django.conf import settings

        self.assertEqual(current_media_root(), settings.MEDIA_ROOT)
