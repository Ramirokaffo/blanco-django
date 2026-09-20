# Blanco en application Windows (.exe)

Ce document explique comment transformer le projet Django en une application
Windows installable : une icône sur le Bureau, un double clic, le serveur
démarre et le navigateur s'ouvre sur Blanco.

## 1. Ce que l'utilisateur final obtient

Un installeur `Blanco-Setup-1.0.0.exe` (~60–90 Mo) qui :

- installe l'application dans `C:\Program Files\Blanco` ;
- pose un raccourci **Menu Démarrer** et, au choix, **Bureau** ;
- ouvre le pare-feu Windows pour que l'application mobile puisse joindre le
  poste par le réseau local (le QR code affiché dans Blanco) ;
- installe un désinstalleur classique (Paramètres → Applications).

Au double clic sur l'icône, l'application :

1. crée sa base de données au premier lancement (aucun serveur à installer,
   c'est du SQLite) et son compte administrateur ;
2. démarre le serveur web local ;
3. ouvre le navigateur par défaut sur `http://127.0.0.1:8000/` ;
4. affiche une petite fenêtre « Blanco » : elle rappelle l'adresse à utiliser
   depuis le téléphone et sert à **arrêter** le serveur. Fermer l'onglet du
   navigateur n'arrête pas Blanco ; fermer cette fenêtre, si.

Au tout premier démarrage, une boîte de dialogue affiche l'identifiant et le
mot de passe administrateur générés. Ils sont aussi écrits dans
`%LOCALAPPDATA%\Blanco\identifiants-admin.txt`.

## 2. Prérequis pour compiler

La compilation doit se faire **sur une machine Windows 64 bits** : PyInstaller
ne fait pas de compilation croisée depuis Linux.

| Outil | Version | Rôle |
|---|---|---|
| [Python](https://www.python.org/downloads/windows/) | 3.11 ou 3.12 | « Add python.exe to PATH » à cocher |
| [Inno Setup 6](https://jrsoftware.org/isdl.php) | 6.x | Construit l'installeur (facultatif) |

## 3. Compiler

Depuis la racine du dépôt, dans PowerShell :

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_windows.ps1
```

Le script enchaîne : environnement virtuel → dépendances
(`requirements.txt` + `requirements-windows.txt`) → `makemigrations` →
`translations compile` → `collectstatic` → PyInstaller → Inno Setup.

Résultats :

- `dist\Blanco\Blanco.exe` — application utilisable telle quelle (copiable sur
  une clé USB avec son dossier) ;
- `installer\Output\Blanco-Setup-1.0.0.exe` — l'installeur à distribuer.

Options : `-Version 1.2.3` fixe le numéro de version (1.0.0 par défaut),
`-Channel test` produit un installeur suffixé `-test`, `-SkipInstaller`
s'arrête après le `.exe`, `-Clean` repart d'un cache PyInstaller vierge (à
utiliser après toute modification de `blanco.spec`).

Sans Inno Setup, le script s'arrête proprement après le `.exe` et le signale.

### Remplacer l'icône

Déposez votre propre `installer\blanco.ico` (multi-tailles 16→256) : la
compilation le reprend tel quel. Le fichier livré est généré par
`python installer\make_icon.py` (monogramme orange sur la couleur primaire de
l'interface).

### Changer le numéro de version

En ligne de commande (`-Version 1.2.3`), ou automatiquement à partir du tag Git
en passant par la CI (section 8). La valeur de repli quand rien n'est fourni
est `AppVersion` en haut de `installer\blanco.iss`.

Ne touchez **jamais** à `AppId` : c'est lui qui permet aux versions suivantes
de se réinstaller par-dessus l'ancienne au lieu de se dupliquer dans la liste
des programmes.

## 4. Où vivent les données

Tout ce qui est écrit à l'exécution va dans `%LOCALAPPDATA%\Blanco`
(typiquement `C:\Users\<nom>\AppData\Local\Blanco`) :

| Fichier | Contenu |
|---|---|
| `db.sqlite3` | toute la base de données |
| `media\` | logo de l'entreprise, photos de produits, QR code serveur |
| `.env` | configuration (port, clé secrète, base de données) |
| `logs\blanco.log` | journal de démarrage et erreurs |
| `identifiants-admin.txt` | identifiants du premier démarrage |

Conséquences pratiques :

- **Sauvegarde** = copier ce dossier (application fermée).
- **Désinstaller ne supprime pas les données.** Réinstaller retrouve la base
  existante. Pour repartir de zéro, supprimez le dossier à la main.
- Chaque compte Windows a ses propres données.

## 5. Configuration

Le `.env` est créé au premier démarrage avec des valeurs saines ; éditez-le
(puis relancez Blanco) pour :

- `BLANCO_PORT` — changer le port d'écoute (8000 par défaut) ;
- `BLANCO_OPEN_BROWSER=False` — ne pas ouvrir le navigateur au démarrage ;
- `DATABASE_ENGINE=django.db.backends.mysql` + les variables `MYSQL_*` —
  utiliser un MySQL existant au lieu de SQLite (plusieurs postes partageant la
  même base).

Variables d'environnement utiles, à définir avant le lancement :

- `BLANCO_DATA_DIR` — déplacer le dossier de données (installation portable
  sur clé USB : `set BLANCO_DATA_DIR=E:\donnees-blanco` dans un `.bat`) ;
- `BLANCO_HEADLESS=1` — démarrer sans la fenêtre de contrôle (serveur en
  arrière-plan, arrêt par Ctrl+C ou le gestionnaire des tâches).

## 6. Accès depuis l'application mobile

Le serveur écoute sur toutes les interfaces : le téléphone connecté au **même
Wi‑Fi** scanne le QR code affiché dans Blanco et se connecte. Si ça ne
fonctionne pas :

1. vérifiez que la case « Autoriser l'accès depuis l'application mobile » a été
   cochée à l'installation (sinon : `netsh advfirewall firewall add rule
   name="Blanco" dir=in action=allow program="C:\Program Files\Blanco\Blanco.exe"
   enable=yes profile=private,domain` dans une invite administrateur) ;
2. vérifiez que le réseau Wi‑Fi est déclaré **privé** dans Windows : le profil
   « public » bloque les connexions entrantes ;
3. l'adresse IP change quand le poste change de réseau — le QR code se
   régénère au démarrage, il suffit de le rescanner.

## 7. Dépannage

**L'application ne s'ouvre pas / se ferme aussitôt.** Tout est dans
`%LOCALAPPDATA%\Blanco\logs\blanco.log` : la dernière trace donne la cause.

**« Windows a protégé votre ordinateur » (SmartScreen).** L'installeur n'est
pas signé numériquement. « Informations complémentaires » → « Exécuter quand
même ». Pour supprimer l'avertissement chez tous les clients, il faut acheter
un certificat de signature de code et ajouter `SignTool` à la compilation.

**Le port 8000 est déjà utilisé.** Blanco prend automatiquement le port libre
suivant et le QR code reflète le port réel. Pour forcer un port, modifiez
`BLANCO_PORT` dans le `.env`.

**Double lancement.** Un second double clic ne démarre pas un second serveur :
il rouvre simplement le navigateur sur l'instance existante.

**Un antivirus met le `.exe` en quarantaine.** C'est un faux positif courant
sur les exécutables PyInstaller non signés ; ajoutez une exclusion sur
`C:\Program Files\Blanco`.

## 8. Publication automatique (GitHub Actions)

`.github/workflows/build-windows.yml` compile et publie une release à chaque
tag poussé :

| Tag poussé | Résultat |
|---|---|
| `test-v1.2.3` | `Blanco-Setup-1.2.3-test.exe`, release marquée **pre-release** |
| `prod-v1.2.3` | `Blanco-Setup-1.2.3.exe`, release normale |

```bash
git tag prod-v1.2.3
git push origin prod-v1.2.3
```

Le job tourne sur `windows-latest` et enchaîne : dépendances →
`makemigrations` → **`manage.py test core`** (une suite rouge bloque la
publication) → Inno Setup → `installer\build_windows.ps1` → release GitHub
avec l'installeur et l'archive portable.

La CI appelle exactement le script de compilation manuelle : ce qui est publié
sort du même chemin que ce que vous obtenez sur votre poste.

Points à connaître :

- **Le numéro de version doit être purement numérique** (`1`, `1.2`, `1.2.3`,
  `1.2.3.4`) : c'est une contrainte d'Inno Setup et de Windows. Un
  `prod-v1.2.3-rc1` est rejeté avec un message explicite — une release
  candidate passe par le canal `test-v*`.
- L'onglet **Actions** → *Build Windows* → *Run workflow* permet de compiler
  une version à la main (version et canal au choix) : les fichiers sont alors
  déposés en artefacts de build, sans créer de release.
- Relancer un job sur un tag déjà publié ne casse rien : les fichiers de la
  release existante sont remplacés.
- Les deux canaux installent **la même application** (même `AppId`, même
  dossier de données) : une préversion installée sur un poste réel migre la
  base de production. Les notes de release le rappellent. Si vous voulez un
  jour des installations côte à côte, il faut un `AppId` et un dossier de
  données distincts par canal.

## 9. Limites connues

- L'exécutable n'est **pas signé** (voir SmartScreen ci-dessus).
- Compilation **64 bits uniquement**.
- Blanco tourne comme une application de bureau, pas comme un **service
  Windows** : il faut une session ouverte. Pour un poste serveur allumé en
  permanence, cochez « Démarrer automatiquement à l'ouverture de session » à
  l'installation, ou passez par NSSM pour en faire un vrai service.
- Les libellés de la fenêtre de contrôle sont en français uniquement : elle
  s'affiche avant l'initialisation de Django, donc hors du système de
  traduction de l'application (qui reste bilingue FR/EN, lui).
