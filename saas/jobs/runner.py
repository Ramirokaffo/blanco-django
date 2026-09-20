"""
Moteur d'exécution des travaux différés.

Concurrence
-----------
La prise d'un travail est sérialisée par ``SELECT ... FOR UPDATE SKIP LOCKED``
(MySQL 8, PostgreSQL) : plusieurs processus de travail peuvent tourner côte à
côte sans se marcher dessus ni se bloquer. SQLite ne connaît pas cette clause —
``select_for_update`` y est un no-op, ce qui reste correct puisqu'un
développement local n'exécute qu'un seul processus.

Reprise sur incident
--------------------
Un travail passé en ``RUNNING`` dont le bail a expiré (processus tué, machine
redémarrée) est remis en file **avec son ``step`` conservé** : la reprise
repart de l'étape suivante et ne rejoue pas ce qui a déjà abouti.
"""

import logging
import os
import socket
import time

from django.db import transaction
from django.utils import timezone

from saas.constants import JOB_BAIL_SECONDES
from saas.jobs import handler_pour
from saas.models import JobKind, JobStatus, ProvisioningJob

logger = logging.getLogger(__name__)


def identite_processus() -> str:
    """Identifie le processus qui détient un bail."""
    return f"{socket.gethostname()}:{os.getpid()}"[:100]


def liberer_baux_expires() -> int:
    """
    Remet en file les travaux dont le processus est mort.

    Retourne le nombre de travaux libérés.
    """
    limite = timezone.now() - timezone.timedelta(seconds=JOB_BAIL_SECONDES)
    return ProvisioningJob.objects.filter(
        status=JobStatus.RUNNING, locked_at__lt=limite
    ).update(status=JobStatus.QUEUED, locked_by="", locked_at=None)


def prendre_un_job(natures=None):
    """
    Réserve le prochain travail à exécuter, ou ``None``.

    La réservation et le changement d'état se font dans une seule transaction :
    aucun autre processus ne peut prendre le même travail.
    """
    maintenant = timezone.now()
    with transaction.atomic():
        requete = (
            ProvisioningJob.objects.select_for_update(skip_locked=True)
            .filter(status=JobStatus.QUEUED, run_after__lte=maintenant)
            .order_by("-priority", "run_after", "pk")
        )
        if natures:
            requete = requete.filter(kind__in=natures)

        job = requete.first()
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.locked_by = identite_processus()
        job.locked_at = maintenant
        job.started_at = job.started_at or maintenant
        job.attempts += 1
        job.save(update_fields=[
            "status", "locked_by", "locked_at", "started_at", "attempts",
        ])
        return job


def executer(job) -> bool:
    """
    Exécute un travail réservé. Retourne ``True`` s'il a abouti.

    Un échec est réessayé selon des paliers croissants, jusqu'à
    ``max_attempts``. Au-delà, le travail est marqué ``FAILED`` et attend une
    reprise manuelle depuis le back-office.
    """
    try:
        resultat = handler_pour(job.kind)(job)
    except Exception as exc:
        logger.exception("Travail #%s (%s) en échec", job.pk, job.kind)
        job.last_error = f"{type(exc).__name__}: {exc}"[:5000]
        job.locked_by = ""
        job.locked_at = None

        if job.peut_reessayer:
            job.status = JobStatus.QUEUED
            job.run_after = timezone.now() + timezone.timedelta(
                seconds=job.prochain_delai()
            )
        else:
            job.status = JobStatus.FAILED
            job.finished_at = timezone.now()
        job.save()
        return False

    # Les travaux d'envoi d'e-mail portent parfois un jeton en clair dans leur
    # charge utile (lien d'invitation) : une fois partis, on ne les conserve
    # pas. Le journal d'audit garde la trace de l'envoi.
    if job.kind == JobKind.MAIL:
        job.delete()
        return True

    job.status = JobStatus.SUCCEEDED
    job.result = resultat or {}
    job.last_error = ""
    job.locked_by = ""
    job.locked_at = None
    job.finished_at = timezone.now()
    job.save()
    return True


def boucle(natures=None, intervalle=2.0, max_jobs=None, once=False):
    """
    Boucle principale du processus de travail.

    ``max_jobs`` et ``once`` servent aux tests et aux exécutions ponctuelles.
    Retourne le nombre de travaux traités.
    """
    traites = 0
    while True:
        job = prendre_un_job(natures)
        if job is None:
            liberer_baux_expires()
            if once or (max_jobs is not None and traites >= max_jobs):
                return traites
            time.sleep(intervalle)
            continue

        executer(job)
        traites += 1

        if max_jobs is not None and traites >= max_jobs:
            return traites
        if once:
            return traites
