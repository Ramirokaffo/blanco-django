"""
Registre des travaux différés.

Chaque nature de travail (``JobKind``) est associée à une fonction qui reçoit
le travail et retourne un dictionnaire de résultat. Les fonctions sont
importées **paresseusement** : le registre est consulté au moment de
l'exécution, jamais au chargement de l'application.
"""

from saas.models import JobKind


def _handler_mail(job):
    from saas.services.mail_service import executer_job_mail

    return executer_job_mail(job)


def _handler_provision(job):
    from saas.services.provisioning_service import executer_job_provision

    return executer_job_provision(job)


#: Nature du travail → fonction d'exécution.
REGISTRE = {
    JobKind.MAIL: _handler_mail,
    JobKind.PROVISION: _handler_provision,
}


class NatureInconnue(RuntimeError):
    """Aucun gestionnaire n'est enregistré pour cette nature de travail."""


def handler_pour(kind):
    try:
        return REGISTRE[kind]
    except KeyError as exc:
        raise NatureInconnue(
            "Aucun gestionnaire pour la nature de travail « %s »." % kind
        ) from exc
