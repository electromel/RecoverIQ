"""Accès aux secrets via ``keyring`` (Gestionnaire d'identifiants Windows).

Les secrets ne sont jamais écrits en base ni dans un fichier en clair.
Les clés de fournisseurs IA (étape 3) passeront par ce même module.
"""

from __future__ import annotations

import logging

import keyring
from keyring.errors import PasswordDeleteError

log = logging.getLogger(__name__)

SERVICE = "RecoverIQ"
GARMIN_PREFIX = "garmin:"


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except Exception:  # backend indisponible : on ne fait pas planter l'appli
        log.exception("Lecture du secret %s impossible", name)
        return None


def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass  # déjà absent


# --- Raccourcis Garmin -------------------------------------------------------

def set_garmin_password(email: str, password: str) -> None:
    set_secret(GARMIN_PREFIX + email.lower(), password)


def get_garmin_password(email: str) -> str | None:
    return get_secret(GARMIN_PREFIX + email.lower())


def delete_garmin_password(email: str) -> None:
    delete_secret(GARMIN_PREFIX + email.lower())
