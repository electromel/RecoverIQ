"""Journalisation : console + fichier tournant dans le dossier de données."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from recoveriq.config import Settings


def setup_logging(cfg: Settings) -> None:
    cfg.ensure_dirs()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        file_handler = RotatingFileHandler(
            cfg.log_dir / "recoveriq.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # garminconnect journalise une trace complète (logger.exception) pour chaque 404,
    # y compris pour les indicateurs simplement non pris en charge par la montre.
    # Notre wrapper journalise lui-même ces cas de façon concise.
    logging.getLogger("garminconnect").setLevel(logging.CRITICAL)
