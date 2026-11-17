"""Migration unique des données depuis l'ancien emplacement (%LOCALAPPDATA%\\RecoverIQ).

Exécutée au démarrage si le nouveau dossier ne contient pas encore de base. La copie
passe par l'API ``backup`` de SQLite, qui intègre le journal WAL en cours : la copie est
cohérente même si l'ancienne base n'a pas été fermée proprement. L'ancien dossier est
laissé intact ; l'utilisateur peut le supprimer après vérification.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

_DB_NAME = "recoveriq.db"
_TOKENS_NAME = "garmin_tokens.bin"


def migrate_legacy_home(old_home: Path | None, new_home: Path) -> bool:
    """Copie base + tokens de ``old_home`` vers ``new_home``. Renvoie True si migration faite."""
    if old_home is None or old_home.resolve() == new_home.resolve():
        return False
    old_db, new_db = old_home / _DB_NAME, new_home / _DB_NAME
    if new_db.exists() or not old_db.exists():
        return False

    new_home.mkdir(parents=True, exist_ok=True)
    tmp = new_db.with_suffix(".migrating")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(new_db)

    old_tokens = old_home / _TOKENS_NAME
    if old_tokens.exists() and not (new_home / _TOKENS_NAME).exists():
        shutil.copy2(old_tokens, new_home / _TOKENS_NAME)

    log.warning("Données migrées de %s vers %s (l'ancien dossier peut être supprimé)", old_home, new_home)
    return True
