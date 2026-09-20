import os
import sys

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """
        - Branche le chargement des données par défaut (modules applicatifs,
          plan comptable) après chaque `migrate`.
        - Génère le QR code du serveur au démarrage.
        On évite la double exécution en ne lançant que dans le processus principal
        (pas dans le reloader de runserver).
        """
        from core.signals import seed_default_data

        # Déclenché uniquement pour les migrations de l'app core (sender=self)
        post_migrate.connect(
            seed_default_data,
            sender=self,
            dispatch_uid='core.seed_default_data',
        )

        # Le QR code ne sert qu'au mode mono-client : l'application mobile y
        # lit l'IP locale du poste serveur pour le rejoindre sur le réseau du
        # commerce. En plateforme hébergée, il n'y a pas d'IP locale
        # pertinente, l'état de QRCodeService est global au processus (un
        # worker servirait à une société le QR d'une autre) et l'écriture se
        # ferait à un chemin fixe partagé. On ne le génère donc pas.
        from django.conf import settings as django_settings

        if getattr(django_settings, 'IS_SAAS', False):
            return

        # En mode runserver, Django lance 2 processus : le reloader et le serveur.
        # RUN_MAIN='true' indique qu'on est dans le processus fils (le vrai serveur).
        # En production (gunicorn, etc.), RUN_MAIN n'existe pas, donc on exécute aussi.
        is_runserver = 'runserver' in sys.argv
        is_main_process = os.environ.get('RUN_MAIN') == 'true'

        if not is_runserver or is_main_process:
            from core.services.qrcode_service import QRCodeService

            # Port par défaut : BLANCO_PORT (défini par le lanceur de
            # l'application de bureau Windows), sinon le port Django habituel.
            try:
                port = int(os.environ.get('BLANCO_PORT') or 8000)
            except ValueError:
                port = 8000
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
