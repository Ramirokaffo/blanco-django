"""
Amorçage de l'application de bureau (exécutable Windows).

Ce module est importé par ``blanco.settings`` lorsque le programme tourne
« gelé » (PyInstaller, ``sys.frozen``) ou lorsque ``BLANCO_DESKTOP=1``.

Un exécutable installé dans ``C:\\Program Files`` ne peut rien écrire à côté
de lui : la base SQLite, les médias, les logs et le fichier de configuration
vivent donc dans un dossier inscriptible de l'utilisateur
(``%LOCALAPPDATA%\\Blanco``). Ce module :

1. crée ce dossier,
2. crée un ``.env`` au premier démarrage (SECRET_KEY aléatoire),
3. charge ce ``.env`` dans ``os.environ`` pour que python-decouple le lise
   (``Config.get()`` consulte ``os.environ`` en priorité).

Aucune configuration manuelle n'est donc nécessaire pour une installation
SQLite standard ; un utilisateur avancé peut éditer le ``.env`` généré pour
basculer sur MySQL.
"""

import os
import secrets
import sys
from pathlib import Path

APP_NAME = "Blanco"

#: Nom du fichier de configuration créé dans le dossier de données.
ENV_FILENAME = ".env"

#: Valeurs écrites dans le .env au premier démarrage. SECRET_KEY est ajoutée
#: dynamiquement (voir _default_env).
_ENV_TEMPLATE = """\
# Configuration de Blanco (généré automatiquement au premier démarrage).
# Ce fichier n'est jamais écrasé par une mise à jour de l'application.

SECRET_KEY={secret_key}
DEBUG=False
ALLOWED_HOSTS={allowed_hosts}

# Base de données : SQLite par défaut (aucun serveur à installer).
# Pour utiliser MySQL, remplacer par django.db.backends.mysql
# et renseigner les variables MYSQL_* ci-dessous.
DATABASE_ENGINE={database_engine}
MYSQL_DATABASE={mysql_database}
MYSQL_USER={mysql_user}
MYSQL_PASSWORD={mysql_password}
MYSQL_HOST={mysql_host}
MYSQL_PORT={mysql_port}

# Port d'écoute du serveur local (0 = choix automatique si occupé).
BLANCO_PORT={port}
# Ouvrir le navigateur au démarrage (True/False).
BLANCO_OPEN_BROWSER=True
"""


def is_desktop() -> bool:
    """Vrai si l'on tourne dans l'exécutable packagé (ou en simulation)."""
    return bool(getattr(sys, "frozen", False)) or os.environ.get("BLANCO_DESKTOP") == "1"


def get_data_dir() -> Path:
    """
    Dossier inscriptible contenant base de données, médias, logs et .env.

    Priorité à ``BLANCO_DATA_DIR`` (utile pour une installation portable sur
    clé USB : il suffit de définir la variable dans un .bat de lancement).
    """
    override = os.environ.get("BLANCO_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / APP_NAME

    # Développement / Linux : conforme à la spécification XDG.
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / APP_NAME.lower()


def _default_env() -> dict:
    """Valeurs par défaut d'une installation de bureau mono-poste."""
    return {
        "secret_key": secrets.token_urlsafe(50),
        "allowed_hosts": "localhost,127.0.0.1",
        "database_engine": "django.db.backends.sqlite3",
        "mysql_database": "",
        "mysql_user": "",
        "mysql_password": "",
        "mysql_host": "",
        "mysql_port": "",
        "port": "8000",
    }


def _parse_env_file(path: Path) -> dict:
    """Lecture minimale d'un fichier .env (KEY=VALUE, # commentaires)."""
    values = {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def ensure_env_file(data_dir: Path) -> Path:
    """Crée le .env au premier démarrage et retourne son chemin."""
    env_path = data_dir / ENV_FILENAME
    if not env_path.exists():
        env_path.write_text(_ENV_TEMPLATE.format(**_default_env()), encoding="utf-8")
        # Lisible par le seul utilisateur courant (sans effet notable sous Windows).
        try:
            env_path.chmod(0o600)
        except OSError:
            pass
    return env_path


def bootstrap() -> Path:
    """
    Prépare le dossier de données et charge la configuration dans os.environ.

    Idempotent : peut être appelé par le lanceur puis par les settings.
    Retourne le dossier de données.
    """
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "media").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)

    env_path = ensure_env_file(data_dir)

    # Les variables déjà présentes dans l'environnement réel gagnent :
    # elles permettent de surcharger ponctuellement la configuration.
    for key, value in _parse_env_file(env_path).items():
        os.environ.setdefault(key, value)

    # Filets de sécurité : blanco.settings exige ces variables sans valeur par
    # défaut (un .env tronqué à la main ne doit pas empêcher le démarrage).
    fallbacks = {
        "SECRET_KEY": secrets.token_urlsafe(50),
        "DEBUG": "False",
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DATABASE_ENGINE": "django.db.backends.sqlite3",
        "MYSQL_DATABASE": "",
        "MYSQL_USER": "",
        "MYSQL_PASSWORD": "",
        "MYSQL_HOST": "",
        "MYSQL_PORT": "",
    }
    for key, value in fallbacks.items():
        os.environ.setdefault(key, value)

    os.environ.setdefault("BLANCO_DATA_DIR", str(data_dir))
    return data_dir
