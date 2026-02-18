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


import subprocess
import platform


class QRCodeService:
    """Gère la génération et le stockage du QR code serveur."""

    # Stockage en mémoire du QR code (base64) et de l'adresse
    _qr_base64: str = None
    _server_address: str = None

    @staticmethod
    def get_local_ip():
        try:
            system = platform.system()

            if system == "Linux":
                result = subprocess.check_output(
                    "ip route get 1 | awk '{print $7; exit}'",
                    shell=True
                )
                return result.decode().strip()

            elif system == "Darwin":
                result = subprocess.check_output(
                    "ipconfig getifaddr en0",
                    shell=True
                )
                return result.decode().strip()

            elif system == "Windows":
                result = subprocess.check_output(
                    "powershell -Command \"(Get-NetIPAddress -AddressFamily IPv4 | "
                    "Where-Object {$_.IPAddress -notlike '169.*' -and $_.IPAddress -notlike '127.*'} | "
                    "Select-Object -First 1 -ExpandProperty IPAddress)\"",
                    shell=True
                )
                return result.decode().strip()

        except Exception:
            return "127.0.0.1"

    
    # def get_local_ip() -> str:
    #     """
    #     Détecte l'adresse IP locale de la machine.
    #     Reproduit WIFIService.get_local_ip() de l'ancienne application.
    #     """
    #     print("settings.DEBUG", settings.DEBUG)
    #     if settings.DEBUG:
    #         s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #         try:
    #             s.connect(("192.255.255.255", 1))
    #             ip = s.getsockname()[0]
    #         except Exception:
    #             ip = "127.0.0.1"
    #         finally:
    #             s.close()
    #     else:
    #         ip = socket.gethostbyname("host.docker.internal")
    #         print('socket.gethostbyname("host.docker.internal")', ip)
    #     return ip

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
    def get_qr_base64(cls) -> str:
        """Retourne le QR code en base64 (ou None si pas encore généré)."""
        return cls._qr_base64

    @classmethod
    def get_server_address(cls) -> str:
        """Retourne l'adresse IP:port du serveur."""
        return cls._server_address

