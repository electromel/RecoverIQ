"""Connexion SQLite et migrations.

Choix : ``sqlite3`` standard plutôt qu'un ORM. Le modèle est simple (tables
par jour) et les upserts « fusionnants » s'écrivent plus clairement en SQL.

Chaque appel à :func:`connect` ouvre une connexion dédiée : SQLite gère
la concurrence lecture/écriture entre threads grâce au mode WAL.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

# Version du schéma de base (schema.sql). Les évolutions suivantes sont des migrations :
# {version cible: fichier SQL du paquet recoveriq.db}, appliquées dans l'ordre, une seule fois
# (PRAGMA user_version), y compris sur une base neuve.
SCHEMA_VERSION = 1
MIGRATIONS: dict[int, str] = {
    2: "migration_002_ai.sql",   # étape 3 : rapports d'analyse IA
    3: "migration_003_readiness_event.sql",   # relevés Readiness horodatés (récupération après effort)
    4: "migration_004_device.sql",   # montre de chaque activité, nom des modèles
    5: "migration_005_more_metrics.sql",   # sommeil (FC, besoin), meilleurs temps, seuil lactique
    6: "migration_006_fitness_age.sql",   # âge de forme physique, tendance de forme -1 / 0 / +1
}

_db_path: Path | None = None


def init_db(path: Path) -> None:
    """Crée ou migre la base. À appeler une fois au démarrage."""
    global _db_path
    _db_path = path
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current == 0:
            schema = resources.files("recoveriq.db").joinpath("schema.sql").read_text("utf-8")
            conn.executescript(schema)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            current = SCHEMA_VERSION
        for version in sorted(v for v in MIGRATIONS if v > current):
            script = resources.files("recoveriq.db").joinpath(MIGRATIONS[version]).read_text("utf-8")
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version={version}")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Connexion transactionnelle : commit en sortie normale, rollback sur exception."""
    if _db_path is None:
        raise RuntimeError("init_db() n'a pas été appelé")
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
