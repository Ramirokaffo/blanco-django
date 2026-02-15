import os
import sys

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """
        Génère le QR code du serveur au démarrage.
        On évite la double exécution en ne lançant que dans le processus principal
        (pas dans le reloader de runserver).
        """
        # En mode runserver, Django lance 2 processus : le reloader et le serveur.
        # RUN_MAIN='true' indique qu'on est dans le processus fils (le vrai serveur).
        # En production (gunicorn, etc.), RUN_MAIN n'existe pas, donc on exécute aussi.
        is_runserver = 'runserver' in sys.argv
        is_main_process = os.environ.get('RUN_MAIN') == 'true'

        if not is_runserver or is_main_process:
            from core.services.qrcode_service import QRCodeService

            port = 8000  # Port par défaut Django
            # Essayer de récupérer le port depuis les arguments de runserver
            for i, arg in enumerate(sys.argv):
                if arg == 'runserver' and i + 1 < len(sys.argv):
                    parts = sys.argv[i + 1].split(':')
                    if len(parts) == 2 and parts[1].isdigit():
                        port = int(parts[1])
                    elif parts[0].isdigit():
                        port = int(parts[0])

            qr_base64 = QRCodeService.generate_server_qr(port=port)
            addr = QRCodeService.get_server_address()
            print(f"\n✅ QR Code serveur généré pour : {addr}\n")
