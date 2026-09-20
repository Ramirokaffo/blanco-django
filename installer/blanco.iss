; Installeur Windows de Blanco (Inno Setup 6).
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\blanco.iss
;
; Compile dist\Blanco\ (produit par PyInstaller) en un installeur unique
; installer\Output\Blanco-Setup-<version>.exe qui pose les raccourcis Menu
; Démarrer / Bureau, ouvre le pare-feu pour l'application mobile et fournit
; un désinstalleur.

#define AppName "Blanco"
#define AppPublisher "Blanco"
#define AppExeName "Blanco.exe"
#define SourceDir "..\dist\Blanco"

; Version et canal sont injectés par la ligne de commande :
;   ISCC.exe /DAppVersion=1.2.3 /DChannel=test installer\blanco.iss
; (installer\build_windows.ps1 -Version 1.2.3 -Channel test s'en charge).
; Les valeurs ci-dessous ne servent qu'à une compilation manuelle.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Channel
  #define Channel ""
#endif

; Une préversion porte son canal dans le nom du fichier, pour qu'on ne
; confonde jamais un installeur de test avec celui livré à la boutique.
#if Len(Channel) > 0
  #define OutputName "Blanco-Setup-" + AppVersion + "-" + Channel
#else
  #define OutputName "Blanco-Setup-" + AppVersion
#endif

[Setup]
; Ne jamais changer cet identifiant : c'est lui qui permet aux versions
; suivantes de se réinstaller par-dessus au lieu de se dupliquer.
AppId={{B7C949C7-9098-478B-AD43-CB20E51B3310}
AppName={#AppName}
AppVersion={#AppVersion}
#if Len(Channel) > 0
AppVerName={#AppName} {#AppVersion} ({#Channel})
#endif
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=Output
OutputBaseFilename={#OutputName}
SetupIconFile=blanco.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Droits administrateur : installation dans Program Files et règle de pare-feu.
PrivilegesRequired=admin
; L'exécutable PyInstaller est 64 bits.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Démarrer Blanco automatiquement à l'ouverture de session"; GroupDescription: "Options"; Flags: unchecked
Name: "firewall"; Description: "Autoriser l'accès depuis l'application mobile (réseau local)"; GroupDescription: "Options"

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
; Règle de pare-feu entrante : sans elle, Windows bloque le téléphone qui
; scanne le QR code (le serveur écoute sur 0.0.0.0).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExeName}"" enable=yes profile=private,domain"; Flags: runhidden; StatusMsg: "Configuration du pare-feu…"; Tasks: firewall
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; RunOnceId: "DelFirewallRule"

[UninstallDelete]
; Fichiers générés à l'exécution dans le dossier d'installation (aucun en
; principe, mais évite de laisser un dossier vide).
Type: filesandordirs; Name: "{app}"

[Messages]
french.WelcomeLabel2=Cet assistant va installer [name/ver] sur votre ordinateur.%n%nLes données (base, médias, configuration) sont conservées dans votre profil utilisateur et ne sont pas supprimées par une désinstallation.
