# -*- mode: python ; coding: utf-8 -*-
"""
Recette PyInstaller de l'application de bureau Blanco (Windows).

    pyinstaller blanco.spec --noconfirm

Produit dist/Blanco/Blanco.exe (mode « onedir » : démarrage nettement plus
rapide qu'un exécutable unique, et c'est l'installeur Inno Setup qui masque
l'arborescence à l'utilisateur final).

Prérequis avant de lancer la compilation — automatisés par
installer/build_windows.ps1 :

  * python manage.py makemigrations core   (les migrations sont désormais
    versionnées : cette étape est un filet de sécurité, normalement sans effet) ;
  * python manage.py translations compile  (fichiers .mo, sinon l'anglais
    retombe silencieusement en français) ;
  * python manage.py collectstatic         (le stockage manifeste de
    WhiteNoise exige staticfiles.json).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_DIR = Path(SPECPATH)
ICON = PROJECT_DIR / "installer" / "blanco.ico"


def project_modules(package: str) -> list:
    """
    Liste les modules d'un paquet du projet par parcours du disque.

    collect_submodules() importerait chaque module pour le découvrir, ce qui
    échoue pour tout ce qui touche aux modèles ou aux réglages tant que
    django.setup() n'a pas tourné (core.serializers, core.models, …). Le
    parcours de fichiers donne la liste complète sans rien exécuter.
    """
    root = PROJECT_DIR / package
    modules = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(PROJECT_DIR).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules.append(".".join(parts))
    return modules

# ── Données embarquées ────────────────────────────────────────────────
# Les gabarits sont chargés par nom à l'exécution : l'analyse statique de
# PyInstaller ne peut pas les deviner.
datas = [
    (str(PROJECT_DIR / "core" / "templates"), "core/templates"),
    (str(PROJECT_DIR / "staticfiles"), "staticfiles"),
    (str(PROJECT_DIR / "locale"), "locale"),
    (str(ICON), "installer"),
]

# Gabarits de l'admin Django et de DRF, catalogues de traduction de Django.
datas += collect_data_files("django")
datas += collect_data_files("rest_framework")
# Fuseaux horaires : Windows n'a pas de base système et le projet tourne en
# Africa/Douala (zoneinfo lèverait ZoneInfoNotFoundError).
datas += collect_data_files("tzdata")

# ── Imports invisibles pour l'analyse statique ────────────────────────
# Django résout applications, migrations, commandes et backends par chaîne de
# caractères ; il faut donc les déclarer explicitement.
hiddenimports = []
hiddenimports += project_modules("blanco")             # dont blanco.settings
hiddenimports += project_modules("core")               # modèles, migrations, commandes
hiddenimports += collect_submodules("django.contrib.admin")
hiddenimports += collect_submodules("django.contrib.auth")
hiddenimports += collect_submodules("django.contrib.contenttypes")
hiddenimports += collect_submodules("django.contrib.sessions")
hiddenimports += collect_submodules("django.contrib.messages")
hiddenimports += collect_submodules("django.contrib.staticfiles")
hiddenimports += collect_submodules("django.core.management.commands")
hiddenimports += collect_submodules("django.db.backends.sqlite3")
hiddenimports += collect_submodules("django.db.backends.mysql")
hiddenimports += collect_submodules("rest_framework")
hiddenimports += collect_submodules("rest_framework.authtoken")
# whitenoise.middleware est désigné par une chaîne dans MIDDLEWARE, et waitress
# charge ses composants dynamiquement : les deux échappent à l'analyse statique.
hiddenimports += collect_submodules("whitenoise")
hiddenimports += collect_submodules("waitress")
hiddenimports += ["pymysql", "tzdata"]

# La commande `translations` n'a de sens qu'au moment de la compilation et
# tirerait toute la base de données locales de Babel dans l'exécutable.
hiddenimports = [name for name in hiddenimports if not name.endswith("commands.translations")]

a = Analysis(
    ["blanco_desktop.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "babel",        # cf. commande translations ci-dessus
        "tkinter.test",
        "pydoc_data",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Blanco",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Application fenêtrée : pas de console noire derrière l'interface.
    # Les traces partent dans %LOCALAPPDATA%\Blanco\logs\blanco.log.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Blanco",
)
