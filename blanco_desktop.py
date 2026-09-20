#!/usr/bin/env python
"""
Lanceur de l'application de bureau Blanco (exécutable Windows).

C'est le point d'entrée compilé par PyInstaller (voir blanco.spec). Au double
clic sur l'icône, il :

1. prépare le dossier de données inscriptible (%LOCALAPPDATA%\\Blanco) ;
2. détecte une instance déjà lancée (dans ce cas il ouvre simplement le
   navigateur et s'arrête) ;
3. applique les migrations (ce qui déclenche l'amorçage des modules
   applicatifs et du plan comptable via le signal post_migrate) ;
4. crée le compte « admin » au tout premier démarrage et affiche son mot de
   passe une seule fois ;
5. démarre le serveur WSGI Waitress sur 0.0.0.0 (le téléphone doit pouvoir
   joindre le poste via le réseau local, cf. QR code) ;
6. ouvre le navigateur par défaut et affiche une petite fenêtre de contrôle.

Lancement en mode développement (sans compiler) :

    BLANCO_DESKTOP=1 python blanco_desktop.py
"""

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

# Doit précéder tout import de Django : blanco.settings lit ce drapeau pour
# basculer sur le dossier de données de l'utilisateur.
os.environ.setdefault("BLANCO_DESKTOP", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blanco.settings")

from blanco.desktop_env import APP_NAME, bootstrap  # noqa: E402

#: Nombre de threads de travail de Waitress (poste unique + application mobile).
WAITRESS_THREADS = 8

#: Taille maximale du journal avant rotation simple (1 Mo).
MAX_LOG_BYTES = 1024 * 1024


# ──────────────────────────────────────────────────────────────────────
# Journalisation
# ──────────────────────────────────────────────────────────────────────

def setup_logging(data_dir: Path):
    """
    Redirige stdout/stderr vers un fichier journal.

    En mode fenêtré, PyInstaller met sys.stdout et sys.stderr à None : sans
    cette redirection, la moindre trace de démarrage serait perdue et un
    diagnostic après coup impossible.
    """
    log_path = data_dir / "logs" / "blanco.log"
    try:
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            log_path.replace(log_path.with_suffix(".log.1"))
        stream = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
    except OSError:
        return None

    sys.stdout = stream
    sys.stderr = stream
    print("\n" + "=" * 70)
    print(f"{APP_NAME} — démarrage {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    return log_path


# ──────────────────────────────────────────────────────────────────────
# Réseau : choix du port et détection d'une instance déjà lancée
# ──────────────────────────────────────────────────────────────────────

def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _blanco_responds(port: int) -> bool:
    """Vrai si une instance de Blanco répond déjà sur ce port."""
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen(f"http://127.0.0.1:{port}/api/test-connection/", timeout=2) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def resolve_port(preferred: int) -> int:
    """
    Retourne le port à utiliser, ou 0 si Blanco tourne déjà sur `preferred`.

    Si le port souhaité est occupé par un autre programme, on prend le premier
    port libre suivant : le QR code (généré au démarrage de l'app Django)
    contient le port réellement utilisé, l'application mobile reste donc
    capable de trouver le serveur.
    """
    if _port_is_free(preferred):
        return preferred
    if _blanco_responds(preferred):
        return 0
    for candidate in range(preferred + 1, preferred + 50):
        if _port_is_free(candidate):
            return candidate
    raise RuntimeError("Aucun port libre trouvé entre %d et %d." % (preferred, preferred + 50))


# ──────────────────────────────────────────────────────────────────────
# Démarrage de Django
# ──────────────────────────────────────────────────────────────────────

def run_migrations():
    """Applique les migrations (et amorce modules + plan comptable OHADA)."""
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=1)


def ensure_admin_account(data_dir: Path):
    """
    Crée le compte « admin » au premier démarrage.

    Retourne le mot de passe généré (à afficher une seule fois) ou None si un
    superutilisateur existe déjà.
    """
    import secrets

    from django.contrib.auth import get_user_model

    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        return None

    password = secrets.token_urlsafe(9)
    User.objects.create_superuser(
        username="admin",
        email="admin@blanco.local",
        password=password,
    )

    # Copie sur disque : la fenêtre peut être fermée trop vite.
    note = data_dir / "identifiants-admin.txt"
    note.write_text(
        "Compte administrateur créé au premier démarrage de Blanco.\n\n"
        "  Utilisateur : admin\n"
        f"  Mot de passe : {password}\n\n"
        "Changez ce mot de passe depuis l'application, puis supprimez ce fichier.\n",
        encoding="utf-8",
    )
    print(f"Compte admin créé, identifiants écrits dans {note}")
    return password


def build_application(data_dir: Path):
    """
    Construit l'application WSGI servie par Waitress.

    Les fichiers statiques sont déjà pris en charge par le middleware
    WhiteNoise. Les médias (logo de l'entreprise, photos de produits) ne le
    sont pas : hors DEBUG, blanco/urls.py ne les route pas. On enveloppe donc
    l'application d'un second WhiteNoise dédié au dossier média, en mode
    autorefresh pour que les images téléversées pendant la session soient
    servies sans redémarrage.
    """
    from django.core.wsgi import get_wsgi_application
    from whitenoise import WhiteNoise

    application = get_wsgi_application()
    media_root = data_dir / "media"
    served = WhiteNoise(application, autorefresh=True)
    served.add_files(str(media_root), prefix="media/")  # add_files ne retourne rien
    return served


def start_server(application, port: int):
    """Démarre Waitress dans un thread démon et retourne l'objet serveur."""
    from waitress.server import create_server

    server = create_server(
        application,
        host="0.0.0.0",
        port=port,
        threads=WAITRESS_THREADS,
        # L'application mobile envoie des photos de produits.
        max_request_body_size=64 * 1024 * 1024,
        ident=APP_NAME,
    )
    thread = threading.Thread(target=server.run, name="waitress", daemon=True)
    thread.start()
    return server


def wait_until_ready(port: int, timeout: float = 20.0) -> bool:
    """Attend que le serveur accepte les connexions avant d'ouvrir le navigateur."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def lan_address(port: int) -> str:
    """Adresse IP:port à saisir sur le téléphone (identique au QR code)."""
    from core.services.qrcode_service import QRCodeService

    return f"{QRCodeService.get_local_ip()}:{port}"


# ──────────────────────────────────────────────────────────────────────
# Fenêtre de contrôle (Tkinter, inclus dans la bibliothèque standard)
# ──────────────────────────────────────────────────────────────────────

class ControlWindow:
    """
    Petite fenêtre « Blanco est en cours d'exécution ».

    Elle donne à l'utilisateur un endroit évident pour rouvrir l'application
    et surtout pour l'arrêter : fermer l'onglet du navigateur ne doit pas
    tuer le serveur, fermer cette fenêtre si.
    """

    def __init__(self, icon_path: Path | None):
        import tkinter as tk

        self._tk = tk
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.root.geometry("420x230")
        if icon_path and icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:  # noqa: BLE001 - icône décorative, jamais bloquante
                pass

        frame = tk.Frame(self.root, padx=20, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        self.status = tk.Label(
            frame,
            text="Démarrage en cours…",
            font=("Segoe UI", 10),
            fg="#555555",
            justify="left",
            wraplength=380,
        )
        self.status.pack(anchor="w", pady=(6, 2))

        self.address = tk.Label(frame, text="", font=("Segoe UI", 9), fg="#777777", justify="left")
        self.address.pack(anchor="w")

        buttons = tk.Frame(frame)
        buttons.pack(side="bottom", anchor="w", pady=(16, 0))
        self.open_button = tk.Button(
            buttons, text="Ouvrir Blanco", width=16, state="disabled", command=self._open
        )
        self.open_button.pack(side="left")
        tk.Button(buttons, text="Quitter", width=12, command=self.quit).pack(side="left", padx=8)

        self.url = None
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def set_running(self, url: str, address: str):
        self.url = url
        self.status.config(text="Le serveur est démarré. Fermez cette fenêtre pour l'arrêter.", fg="#1a7f37")
        self.address.config(text=f"Ce poste : {url}\nTéléphone (même Wi-Fi) : http://{address}")
        self.open_button.config(state="normal")

    def set_failed(self, message: str, log_path: Path | None):
        detail = f"\n\nJournal : {log_path}" if log_path else ""
        self.status.config(text=f"Échec du démarrage.\n{message}{detail}", fg="#b42318")

    def show_first_run_password(self, password: str):
        from tkinter import messagebox

        messagebox.showinfo(
            "Premier démarrage",
            "Un compte administrateur vient d'être créé :\n\n"
            "    Utilisateur : admin\n"
            f"    Mot de passe : {password}\n\n"
            "Notez-le : il ne sera plus affiché. Il est aussi enregistré dans\n"
            "identifiants-admin.txt, dans le dossier de données de Blanco.",
            parent=self.root,
        )

    def _open(self):
        if self.url:
            webbrowser.open(self.url)

    def quit(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()

    def after(self, callback):
        """Exécute un appel dans le thread Tk (seul autorisé à toucher l'IHM)."""
        self.root.after(0, callback)


# ──────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────

def _bundle_dir() -> Path:
    """Dossier des ressources embarquées (ou racine du dépôt en dev)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def boot(data_dir: Path, port: int, open_browser: bool, window: "ControlWindow | None"):
    """Séquence de démarrage complète, exécutée hors du thread de l'IHM."""
    import django

    django.setup()
    run_migrations()
    password = ensure_admin_account(data_dir)
    application = build_application(data_dir)
    start_server(application, port)

    if not wait_until_ready(port):
        raise RuntimeError("Le serveur n'a pas répondu dans le délai imparti.")

    url = f"http://127.0.0.1:{port}/"
    address = lan_address(port)
    print(f"Serveur prêt sur {url} (réseau local : {address})")

    if window is not None:
        window.after(lambda: window.set_running(url, address))
        if password:
            window.after(lambda: window.show_first_run_password(password))
    elif password:
        print(f"Compte admin créé — mot de passe : {password}")

    if open_browser:
        webbrowser.open(url)


def main() -> int:
    data_dir = bootstrap()
    log_path = setup_logging(data_dir)

    # BLANCO_PORT est renseigné par le .env généré au premier démarrage.
    try:
        preferred_port = int(os.environ.get("BLANCO_PORT") or 8000)
    except ValueError:
        preferred_port = 8000
    open_browser = (os.environ.get("BLANCO_OPEN_BROWSER", "True").strip().lower()
                    not in {"false", "0", "no", "non"})

    port = resolve_port(preferred_port)
    if port == 0:
        # Blanco tourne déjà : on se contente de ramener l'utilisateur dessus.
        print("Instance déjà démarrée, ouverture du navigateur.")
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{preferred_port}/")
        return 0

    # Le QR code est généré dans AppConfig.ready() : le port doit être connu avant.
    os.environ["BLANCO_PORT"] = str(port)
    print(f"Port retenu : {port} (souhaité : {preferred_port})")

    icon_path = _bundle_dir() / "installer" / "blanco.ico"
    window = None
    if os.environ.get("BLANCO_HEADLESS") != "1":
        try:
            window = ControlWindow(icon_path)
        except Exception:  # noqa: BLE001 - Tkinter absent : on reste en console
            print("Interface Tkinter indisponible, démarrage en mode console.")
            traceback.print_exc()

    if window is None:
        boot(data_dir, port, open_browser, None)
        print("Serveur en cours d'exécution. Ctrl+C pour arrêter.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("Arrêt demandé.")
        return 0

    def worker():
        try:
            boot(data_dir, port, open_browser, window)
        except Exception as exc:  # noqa: BLE001 - toute erreur doit rester visible
            traceback.print_exc()
            message = str(exc) or exc.__class__.__name__
            window.after(lambda: window.set_failed(message, log_path))

    threading.Thread(target=worker, name="blanco-boot", daemon=True).start()
    window.run()

    # Waitress et les threads Django sont des démons : on coupe court plutôt
    # que d'attendre la fin des connexions maintenues ouvertes par le navigateur.
    print("Arrêt de Blanco.")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
