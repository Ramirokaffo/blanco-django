#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Avant tout : sous Windows, une sortie redirigée est encodée en cp1252 et
    # les emojis des messages de démarrage tueraient la commande.
    from blanco.console import configure_console

    configure_console()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blanco.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
