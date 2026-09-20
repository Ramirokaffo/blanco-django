<#
.SYNOPSIS
    Compile Blanco en application Windows (.exe) puis en installeur.

.DESCRIPTION
    À exécuter SUR UNE MACHINE WINDOWS, depuis la racine du dépôt :

        powershell -ExecutionPolicy Bypass -File installer\build_windows.ps1

    Étapes : environnement virtuel, dépendances, migrations, traductions,
    fichiers statiques, PyInstaller, puis Inno Setup si ISCC.exe est trouvé.

.PARAMETER Version
    Numéro de version de l'installeur (ex. 1.2.3). Injecté dans blanco.iss.

.PARAMETER Channel
    Canal de publication : 'test' pour une préversion (le nom de l'installeur
    devient Blanco-Setup-<version>-test.exe), vide pour une version de
    production. Renseigné automatiquement par la CI à partir du tag Git.

.PARAMETER SkipInstaller
    S'arrête après dist\Blanco\Blanco.exe, sans construire l'installeur.

.PARAMETER RequireInstaller
    Échoue si Inno Setup est absent au lieu de s'arrêter après le .exe.
    Utilisé par la CI, qui ne doit jamais publier une version sans installeur.

.PARAMETER Clean
    Repart d'un dossier build\ et dist\ vierge.
#>
[CmdletBinding()]
param(
    [string]$Version = '1.0.0',
    [ValidateSet('', 'test', 'prod')]
    [string]$Channel = '',
    [switch]$SkipInstaller,
    [switch]$RequireInstaller,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Racine du dépôt = dossier parent de ce script.
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir
Write-Host "Projet  : $ProjectDir" -ForegroundColor Cyan
Write-Host "Version : $Version" -ForegroundColor Cyan

# 'prod' est le cas nominal : pas de suffixe dans le nom de l'installeur.
$InstallerChannel = $Channel
if ($Channel -eq 'prod') {
    $InstallerChannel = ''
}
if ($InstallerChannel -ne '') {
    Write-Host "Canal   : $InstallerChannel (préversion)" -ForegroundColor Cyan
}

# ── 1. Environnement virtuel ──────────────────────────────────────────
$VenvPython = Join-Path $ProjectDir 'venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host '[1/7] Création de l''environnement virtuel…' -ForegroundColor Yellow
    python -m venv venv
}
else {
    Write-Host '[1/7] Environnement virtuel déjà présent.' -ForegroundColor Yellow
}

# ── 2. Dépendances ────────────────────────────────────────────────────
Write-Host '[2/7] Installation des dépendances…' -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r requirements.txt -r requirements-windows.txt --quiet
if ($LASTEXITCODE -ne 0) { throw 'Échec de l''installation des dépendances.' }

# ── 3. Configuration de compilation ───────────────────────────────────
# makemigrations / collectstatic chargent blanco.settings, qui exige ces
# variables. Elles ne servent qu'à la compilation : l'application installée
# génère son propre .env dans %LOCALAPPDATA%\Blanco au premier démarrage.
Write-Host '[3/7] Configuration de compilation…' -ForegroundColor Yellow
$env:SECRET_KEY = 'build-only-secret-key-not-used-at-runtime'
$env:DEBUG = 'False'
$env:ALLOWED_HOSTS = 'localhost,127.0.0.1'
$env:DATABASE_ENGINE = 'django.db.backends.sqlite3'
$env:MYSQL_DATABASE = ''
$env:MYSQL_USER = ''
$env:MYSQL_PASSWORD = ''
$env:MYSQL_HOST = ''
$env:MYSQL_PORT = ''

# ── 4. Migrations (versionnées : filet de sécurité) ───────────────────
# Les migrations sont committées ; cette étape ne doit rien produire. Si elle
# génère un fichier, c'est qu'un modèle a changé sans migration associée —
# --check le signale et interrompt la compilation plutôt que d'embarquer un
# .exe dont le schéma diverge.
Write-Host '[4/7] Contrôle des migrations…' -ForegroundColor Yellow
& $VenvPython manage.py makemigrations core --check --dry-run
if ($LASTEXITCODE -ne 0) {
    throw 'Des modèles ont changé sans migration associée : lancez `manage.py makemigrations core` et commitez le fichier.'
}

# ── 5. Traductions et fichiers statiques ──────────────────────────────
Write-Host '[5/7] Traductions et fichiers statiques…' -ForegroundColor Yellow
& $VenvPython manage.py translations compile
if ($LASTEXITCODE -ne 0) { throw 'Échec de la compilation des traductions.' }
& $VenvPython manage.py collectstatic --noinput --clear
if ($LASTEXITCODE -ne 0) { throw 'Échec de collectstatic.' }

if (-not (Test-Path 'installer\blanco.ico')) {
    & $VenvPython installer\make_icon.py
}

# ── 6. PyInstaller ────────────────────────────────────────────────────
Write-Host '[6/7] Compilation de l''exécutable…' -ForegroundColor Yellow
$PyiArgs = @('blanco.spec', '--noconfirm')
if ($Clean) { $PyiArgs += '--clean' }
& $VenvPython -m PyInstaller @PyiArgs
if ($LASTEXITCODE -ne 0) { throw 'Échec de PyInstaller.' }

$ExePath = Join-Path $ProjectDir 'dist\Blanco\Blanco.exe'
if (-not (Test-Path $ExePath)) { throw "Exécutable introuvable : $ExePath" }
Write-Host "      -> $ExePath" -ForegroundColor Green

if ($SkipInstaller) {
    Write-Host 'Terminé (installeur ignoré).' -ForegroundColor Green
    exit 0
}

# ── 7. Inno Setup ─────────────────────────────────────────────────────
Write-Host '[7/7] Construction de l''installeur…' -ForegroundColor Yellow
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    if ($RequireInstaller) {
        throw 'ISCC.exe introuvable alors que -RequireInstaller est demandé.'
    }
    Write-Warning 'ISCC.exe introuvable : installez Inno Setup 6 (https://jrsoftware.org/isdl.php).'
    Write-Host "L'application reste utilisable telle quelle : $ExePath" -ForegroundColor Green
    exit 0
}

$IsccArgs = @("/DAppVersion=$Version")
if ($InstallerChannel -ne '') {
    $IsccArgs += "/DChannel=$InstallerChannel"
}
$IsccArgs += 'installer\blanco.iss'

& $Iscc @IsccArgs
if ($LASTEXITCODE -ne 0) { throw 'Échec d''Inno Setup.' }

$SetupName = "Blanco-Setup-$Version.exe"
if ($InstallerChannel -ne '') {
    $SetupName = "Blanco-Setup-$Version-$InstallerChannel.exe"
}
$SetupPath = Join-Path $ProjectDir "installer\Output\$SetupName"
if (-not (Test-Path $SetupPath)) { throw "Installeur introuvable : $SetupPath" }
Write-Host "Installeur prêt : $SetupPath" -ForegroundColor Green
