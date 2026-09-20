"""
Écriture du journal d'audit de la plateforme.

Toujours passer par ``log()`` : cette fonction dénormalise ce qu'il faut pour
que la trace reste lisible même après la disparition de l'acteur ou de
l'entreprise, et elle ne lève jamais — un incident de journalisation ne doit
pas faire échouer l'action qu'il documente.
"""

import logging

from saas.models import ActorKind, PlatformAuditLog

logger = logging.getLogger(__name__)


def _adresse_ip(request):
    if request is None:
        return None
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def log(action, *, company=None, actor=None, actor_kind=None, target="",
        metadata=None, request=None):
    """Consigne une action. Ne lève jamais."""
    try:
        etiquette = ""
        identifiant = None
        if actor is not None and getattr(actor, "is_authenticated", False):
            identifiant = actor.pk
            etiquette = f"{actor.get_full_name()} (@{actor.username})"

        PlatformAuditLog.objects.create(
            action=action,
            actor_kind=actor_kind or (
                ActorKind.PLATFORM_STAFF if identifiant else ActorKind.SYSTEM
            ),
            actor_id=identifiant,
            actor_label=etiquette[:200],
            company=company,
            company_slug=(company.slug if company else "")[:40],
            target=str(target)[:200],
            metadata=metadata or {},
            ip=_adresse_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        )
    except Exception:  # pragma: no cover - la journalisation ne doit rien casser
        logger.exception("Écriture du journal d'audit impossible (action=%s)", action)
