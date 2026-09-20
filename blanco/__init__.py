"""
Initialisation du paquet projet.

Le pilote MySQL est installé ICI, et non plus seulement dans ``core/__init__``.

Motif : ``blanco.settings`` doit pouvoir configurer une base MySQL sans avoir
importé ``core`` au préalable. En mode SaaS, l'import de
``core.services.qrcode_service`` en tête des settings — qui tirait ``core`` et
donc le pilote — n'a plus lieu d'être (aucune IP LAN à détecter). Poser le shim
dans ``blanco/__init__`` garantit qu'il est en place avant toute connexion,
quel que soit le mode : le paquet ``blanco`` est toujours importé avant
``blanco.settings``.

``install_as_MySQLdb()`` est idempotent : le double appel avec ``core`` est
sans effet.
"""

import pymysql

# PyMySQL en remplacement de MySQLdb (Django 4.2 ne connaît que MySQLdb).
pymysql.install_as_MySQLdb()

# Django 4.2 refuse mysqlclient < 1.4.3 ; on annonce une version compatible.
pymysql.version_info = (2, 2, 1, "final", 0)
