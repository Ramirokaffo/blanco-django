"""
Service de génération de QR Code contenant l'adresse IP du serveur.
Reproduit le comportement de l'ancienne application :
  - /blanco/Service/QRCodeService.py
  - /blanco/Service/WIFIService.py
"""

import base64
import io
import os
import socket

import qrcode
from django.conf import settings


class QRCodeService:
    """Gère la génération et le stockage du QR code serveur."""

    # Stockage en mémoire du QR code (base64) et de l'adresse
    _qr_base64: str = None
    _server_address: str = None

    @staticmethod
    def get_local_ip() -> str:
        """
        Détecte l'adresse IP locale de la machine.
        Reproduit WIFIService.get_local_ip() de l'ancienne application.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    @staticmethod
    def generate_qr_code(data: str) -> str:
        """
        Génère un QR code à partir de `data` et retourne l'image en base64.
        Reproduit QRCodeService.create_code() de l'ancienne application.
        """
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Sauvegarder dans un buffer mémoire → base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")

    @classmethod
    def generate_server_qr(cls, port: int = 8000) -> str:
        """
        Génère le QR code pour l'adresse IP:port du serveur.
        Appelé au démarrage du serveur.
        """
        ip = cls.get_local_ip()
        cls._server_address = f"{ip}:{port}"
        cls._qr_base64 = cls.generate_qr_code(cls._server_address)

        # Optionnel : sauvegarder aussi le fichier sur disque
        qr_dir = os.path.join(settings.MEDIA_ROOT, "qrcode")
        os.makedirs(qr_dir, exist_ok=True)
        qr_path = os.path.join(qr_dir, "qr-server.png")

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(cls._server_address)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_path)

        return cls._qr_base64

    @classmethod
    def refresh_server_qr(cls) -> dict:
        """
        Vérifie si l'IP locale a changé. Si oui, régénère le QR code,
        met à jour ALLOWED_HOSTS et CORS_ALLOWED_ORIGINS dynamiquement.
        Retourne un dict avec le QR base64, l'adresse et un flag 'changed'.
        """
        current_ip = cls.get_local_ip()

        # Extraire l'IP stockée (sans le port)
        old_ip = None
        port = 8000
        if cls._server_address:
            parts = cls._server_address.split(":")
            old_ip = parts[0]
            if len(parts) == 2 and parts[1].isdigit():
                port = int(parts[1])

        changed = current_ip != old_ip

        if changed:
            # Régénérer le QR code avec la nouvelle IP
            cls.generate_server_qr(port=port)

            # Mettre à jour ALLOWED_HOSTS dynamiquement
            if current_ip not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(current_ip)

            # Mettre à jour CORS_ALLOWED_ORIGINS si configuré
            cors_origins = getattr(settings, "CORS_ALLOWED_ORIGINS", None)
            if cors_origins is not None and current_ip not in cors_origins:
                cors_origins.append(current_ip)

        return {
            "qr_base64": cls._qr_base64,
            "server_address": cls._server_address,
            "changed": changed,
        }

    @classmethod
    def get_qr_base64(cls) -> str:
        """Retourne le QR code en base64 (ou None si pas encore généré)."""
        return cls._qr_base64

    @classmethod
    def get_server_address(cls) -> str:
        """Retourne l'adresse IP:port du serveur."""
        return cls._server_address

