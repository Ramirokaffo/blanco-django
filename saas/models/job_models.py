"""
File de travaux différés.

Pourquoi une table plutôt que Celery
------------------------------------
Le provisionnement d'un espace dure 10 à 30 secondes (le ``migrate`` d'une
quarantaine de tables domine) : trop long pour une requête HTTP, pas assez
volumineux pour justifier un courtier de messages.

Surtout, ce travail est **naturellement à état** : il a des étapes, un point de
reprise, un compteur de tentatives, un message d'erreur, et il doit être
consultable depuis le back-office. Une table offre tout cela ; avec Celery il
faudrait l'écrire de toute façon, **plus** un courtier, une image de travail
supplémentaire et sa supervision.

MySQL 8 fournit ``SELECT ... FOR UPDATE SKIP LOCKED``, ce qui donne une
concurrence sûre entre plusieurs processus de travail en une seule requête.

Une alternative a été écartée explicitement : lancer un fil d'exécution depuis
la vue HTTP. Gunicorn recycle ses processus (``--max-requests``) ; un
redémarrage tuerait le fil en plein ``migrate`` et rien ne pourrait le
relancer. L'état doit vivre en base, et le travail hors du processus web.
"""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from saas.constants import JOB_BACKOFF_SECONDES, JOB_TENTATIVES_MAX


class JobKind(models.TextChoices):
    PROVISION = "PROVISION", _("Création d'un espace")
    MAIL = "MAIL", _("Envoi d'un e-mail")
    BACKUP = "BACKUP", _("Sauvegarde")
    EXPORT = "EXPORT", _("Export client")
    DELETE = "DELETE", _("Suppression d'un espace")
    USAGE_REFRESH = "USAGE_REFRESH", _("Rafraîchissement de l'usage")
    DOMAIN_VERIFY = "DOMAIN_VERIFY", _("Vérification d'un nom d'hôte")


class JobStatus(models.TextChoices):
    QUEUED = "QUEUED", _("En attente")
    RUNNING = "RUNNING", _("En cours")
    SUCCEEDED = "SUCCEEDED", _("Terminé")
    FAILED = "FAILED", _("Échoué")
    CANCELLED = "CANCELLED", _("Annulé")


class ProvisionStep(models.TextChoices):
    """
    Point de reprise du provisionnement.

    Chaque étape est idempotente : reprendre un travail interrompu repart de
    l'étape suivante sans rejouer ce qui a déjà abouti, et sans jamais
    détruire une base à moitié migrée — on la termine.
    """

    CREATE_DB = "CREATE_DB", _("Création de la base")
    MIGRATE = "MIGRATE", _("Installation des tables")
    SEED = "SEED", _("Chargement des données de référence")
    OWNER = "OWNER", _("Création du compte propriétaire")
    DOMAIN = "DOMAIN", _("Mise en service du nom d'hôte")
    DONE = "DONE", _("Terminé")


class ProvisioningJob(models.Model):
    """Un travail à exécuter par le processus ``manage.py run_jobs``."""

    company = models.ForeignKey(
        "saas.Company",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="jobs",
        verbose_name=_("Entreprise"),
    )
    kind = models.CharField(
        max_length=20, choices=JobKind.choices, verbose_name=_("Nature")
    )
    status = models.CharField(
        max_length=12, choices=JobStatus.choices, default=JobStatus.QUEUED,
        verbose_name=_("État"),
    )
    step = models.CharField(
        max_length=20, blank=True, default="", verbose_name=_("Étape atteinte")
    )

    payload = models.JSONField(default=dict, blank=True, verbose_name=_("Paramètres"))
    result = models.JSONField(default=dict, blank=True, verbose_name=_("Résultat"))

    attempts = models.PositiveIntegerField(default=0, verbose_name=_("Tentatives"))
    max_attempts = models.PositiveIntegerField(
        default=JOB_TENTATIVES_MAX, verbose_name=_("Tentatives maximum")
    )
    last_error = models.TextField(blank=True, default="", verbose_name=_("Dernière erreur"))

    run_after = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name=_("À exécuter après")
    )
    priority = models.SmallIntegerField(default=0, verbose_name=_("Priorité"))

    # Bail : identifie le processus qui traite le travail. Un bail expiré
    # signale un processus mort ; le travail repart avec son `step` conservé.
    locked_by = models.CharField(max_length=100, blank=True, default="")
    locked_at = models.DateTimeField(null=True, blank=True)

    create_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "saas_provisioning_job"
        verbose_name = _("Travail")
        verbose_name_plural = _("Travaux")
        ordering = ["-create_at"]
        indexes = [
            models.Index(
                fields=["status", "run_after", "priority"],
                name="saas_job_a_traiter_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} [{self.status}]"

    @property
    def peut_reessayer(self) -> bool:
        return self.attempts < self.max_attempts

    def prochain_delai(self):
        """Attente avant la prochaine tentative (paliers croissants)."""
        indice = min(self.attempts, len(JOB_BACKOFF_SECONDES) - 1)
        return JOB_BACKOFF_SECONDES[indice]
