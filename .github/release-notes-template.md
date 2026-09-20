Application de bureau Windows de Blanco, version `{{VERSION}}`.

## Installation

Téléchargez l'installeur `.exe` ci-dessous, exécutez-le, puis lancez Blanco
depuis le raccourci créé. Au premier démarrage, l'application affiche les
identifiants du compte administrateur : notez-les.

Windows SmartScreen affiche un avertissement, car l'exécutable n'est pas signé
numériquement : **Informations complémentaires** → **Exécuter quand même**.

## Variante portable

Le `.zip` se décompresse où vous voulez et `Blanco.exe` se lance sans
installation — mais sans raccourci, sans désinstalleur et sans règle de
pare-feu (l'application mobile ne pourra pas joindre le poste tant que vous ne
l'ajoutez pas à la main).

## Vos données

La base de données, les médias et la configuration vivent dans
`%LOCALAPPDATA%\Blanco`. Ils survivent aux mises à jour **et** aux
désinstallations : pour sauvegarder Blanco, copiez ce dossier application
fermée.

## Accès depuis l'application mobile

Le téléphone doit être sur le même Wi-Fi, déclaré **réseau privé** dans
Windows. Scannez le QR code affiché dans Blanco.

Configuration détaillée et dépannage : `WINDOWS_README.md`.
