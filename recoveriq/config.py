"""Configuration de l'application.

Toutes les valeurs ont un défaut raisonnable et peuvent être surchargées par
variable d'environnement (préfixe ``RECOVERIQ_``). Aucun secret ici : les
secrets passent par :mod:`recoveriq.secrets_store` et le fichier de tokens chiffré.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_home() -> Path:
    """Dossier des données : %USERPROFILE%\\.recoveriq.

    Volontairement hors d'AppData : si le processus s'exécute dans le contexte d'un
    paquet MSIX (Python du Microsoft Store, ou lancement depuis une application
    empaquetée), Windows redirige silencieusement les écritures dans AppData vers un
    dossier privé du paquet. Les données seraient alors invisibles pour un lancement
    normal et supprimées avec le paquet. Le profil utilisateur n'est pas redirigé.
    """
    return Path.home() / ".recoveriq"


def legacy_home() -> Path | None:
    """Ancien emplacement (version 0.1) : %LOCALAPPDATA%\\RecoverIQ."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "RecoverIQ" if local_app_data else None


def is_packaged_process() -> bool:
    """Vrai si le processus s'exécute dans un paquet MSIX (écritures AppData redirigées)."""
    if sys.platform != "win32":
        return False
    import ctypes

    length = ctypes.c_uint32(0)
    # APPMODEL_ERROR_NO_PACKAGE (15700) : processus non empaqueté.
    result = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
    return result != 15700


def is_under_appdata(path: Path) -> bool:
    roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")]
    resolved = str(path.resolve()).lower()
    return any(root and resolved.startswith(str(Path(root).resolve()).lower()) for root in roots)


def _env(name: str, default: str) -> str:
    return os.environ.get(f"RECOVERIQ_{name}", default)


@dataclass(frozen=True)
class Settings:
    """Paramètres techniques (non modifiables depuis l'interface)."""

    home: Path = field(default_factory=lambda: Path(_env("HOME", str(_default_home()))))
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8765")))

    # Pause minimale entre deux appels Garmin (secondes) + gigue aléatoire.
    request_pause_s: float = field(default_factory=lambda: float(_env("REQUEST_PAUSE", "1.5")))
    request_jitter_s: float = 0.5
    # Nombre de jours resynchronisés à chaque passage (Garmin complète parfois après coup).
    resync_days: int = field(default_factory=lambda: int(_env("RESYNC_DAYS", "3")))
    # Taille des blocs pour les appels « plage de dates » et pour l'import historique.
    range_chunk_days: int = 30
    # Import historique : on arrête de remonter un indicateur après N jours consécutifs sans donnée.
    empty_streak_stop_days: int = field(default_factory=lambda: int(_env("EMPTY_STREAK_STOP", "90")))
    # Nombre max de tentatives d'un même (indicateur, jour) en erreur avant abandon.
    max_attempts: int = 3
    # Date de début d'historique forcée (YYYY-MM-DD) ; vide = date de la première activité.
    history_start: str = field(default_factory=lambda: _env("HISTORY_START", ""))
    # Heure de la synchronisation quotidienne (HH:MM, heure locale).
    daily_sync_time: str = field(default_factory=lambda: _env("DAILY_SYNC_TIME", "06:30"))

    @property
    def db_path(self) -> Path:
        return self.home / "recoveriq.db"

    @property
    def token_path(self) -> Path:
        return self.home / "garmin_tokens.bin"

    @property
    def log_dir(self) -> Path:
        return self.home / "logs"

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
