"""
Envoi des e-mails de la plateforme.

Règle absolue : **jamais d'envoi synchrone depuis une vue.** Un serveur SMTP
lent bloquerait une requête pendant quinze secondes ; un serveur en panne ferait
échouer une inscription pourtant déjà validée. Tout passe donc par la file de
travaux, qui apporte gratuitement les réessais et la visibilité (« l'e-mail
est-il parti ? »).

Langue du destinataire
----------------------
Le rendu se fait sous ``translation.override(langue)``, où la langue vient de
l'entreprise ou de l'invitation — **jamais** de la langue active du processus
de travail, qui n'a aucun rapport avec le destinataire.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation

logger = logging.getLogger(__name__)

#: Gabarits attendus pour chaque message : <nom>_subject.txt, <nom>.txt, <nom>.html
DOSSIER_GABARITS = "emails"


def queue_mail(template, to, context=None, *, company=None, language=None, priority=0):
    """
    Met un e-mail en file d'attente et retourne le travail créé.

    ``context`` doit être sérialisable en JSON : il est stocké dans le travail.
    Il peut contenir un jeton en clair (lien d'invitation) — c'est pourquoi les
    travaux d'envoi réussis sont **supprimés** plutôt que conservés, seule la
    trace d'audit subsistant.
    """
    from saas.models import JobKind, ProvisioningJob

    destinataires = [to] if isinstance(to, str) else list(to)
    return ProvisioningJob.objects.create(
        kind=JobKind.MAIL,
        company=company,
        priority=priority,
        payload={
            "template": template,
            "to": destinataires,
            "context": context or {},
            "language": language or (company.language if company else settings.LANGUAGE_CODE),
        },
    )


def rendre(template, context, language):
    """Rend l'objet et les deux corps (texte et HTML) dans la langue voulue."""
    with translation.override(language):
        sujet = render_to_string(
            f"{DOSSIER_GABARITS}/{template}_subject.txt", context
        ).strip()
        # Un objet d'e-mail ne peut pas contenir de saut de ligne (injection
        # d'en-tête) : on aplatit ce que le gabarit aurait pu laisser passer.
        sujet = " ".join(sujet.split())
        corps_texte = render_to_string(f"{DOSSIER_GABARITS}/{template}.txt", context)
        try:
            corps_html = render_to_string(f"{DOSSIER_GABARITS}/{template}.html", context)
        except Exception:
            corps_html = None
    return sujet, corps_texte, corps_html


def envoyer_maintenant(template, to, context=None, *, language=None):
    """
    Envoi immédiat. Réservé au processus de travail et aux tests.

    Les vues doivent appeler ``queue_mail``.
    """
    context = context or {}
    langue = language or settings.LANGUAGE_CODE
    destinataires = [to] if isinstance(to, str) else list(to)

    sujet, corps_texte, corps_html = rendre(template, context, langue)
    message = EmailMultiAlternatives(
        subject=sujet,
        body=corps_texte,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=destinataires,
    )
    if corps_html:
        message.attach_alternative(corps_html, "text/html")
    message.send(fail_silently=False)
    return len(destinataires)


def executer_job_mail(job):
    """Exécute un travail d'envoi. Appelé par le moteur de travaux."""
    charge = job.payload or {}
    envoyes = envoyer_maintenant(
        charge["template"],
        charge["to"],
        charge.get("context"),
        language=charge.get("language"),
    )
    return {"envoyes": envoyes, "at": timezone.now().isoformat()}
