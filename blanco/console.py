"""
Sortie console tolérante aux encodages hérités (Windows).

Les messages de démarrage du projet contiennent des emojis (« ✅ Données par
défaut… », « ✅ QR Code serveur généré… »). Sous Windows, dès que la sortie
standard n'est pas une console interactive — un pipe, un fichier, un job
GitHub Actions — Python l'encode avec l'encodage local (cp1252), incapable de
représenter ces caractères : la commande meurt sur un ``UnicodeEncodeError``
avant d'avoir rien fait.

``configure_console()`` bascule simplement les flux en mode « remplacement » :
un caractère non représentable devient « ? » au lieu de faire échouer la
commande. L'encodage n'est pas forcé à UTF-8, ce qui produirait du charabia
sur une console Windows héritée ; pour obtenir les emojis intacts dans un
journal, définir ``PYTHONUTF8=1`` dans l'environnement (ce que fait la CI).

À appeler au tout début des points d'entrée (manage.py et les scripts du
dépôt), avant tout import de Django.
"""

import sys


def configure_console() -> None:
    """Rend stdout/stderr incapables d'échouer sur un caractère non encodable."""
    for stream in (sys.stdout, sys.stderr):
        # stream vaut None dans une application PyInstaller fenêtrée, et n'a
        # pas de reconfigure() si quelque chose l'a déjà remplacé.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            # Flux détaché ou non textuel : rien à reconfigurer.
            pass
