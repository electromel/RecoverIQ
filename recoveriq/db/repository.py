"""Accès aux données : toutes les requêtes SQL de l'application passent par ici."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from recoveriq.db.database import table_columns
from recoveriq.metrics import METRICS, METRICS_BY_TABLE


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Tables normalisées
# ---------------------------------------------------------------------------

_columns_cache: dict[str, list[str]] = {}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if table not in _columns_cache:
        _columns_cache[table] = table_columns(conn, table)
    return _columns_cache[table]


def upsert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    """Insère ou fusionne des lignes.

    Fusion « non destructive » : une valeur NULL entrante n'écrase jamais une valeur
    existante. Plusieurs appels Garmin alimentent parfois la même table (ex. résumé
    journalier + série Body Battery) ; chacun complète les colonnes qu'il connaît.
    """
    if table not in METRICS_BY_TABLE:
        raise ValueError(f"Table inconnue : {table}")
    key = METRICS_BY_TABLE[table].key
    allowed = set(_columns(conn, table))
    for row in rows:
        cols = [c for c in row if c in allowed]
        unknown = set(row) - allowed
        if unknown:
            raise ValueError(f"Colonnes inconnues pour {table} : {sorted(unknown)}")
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(
            f"{c} = COALESCE(excluded.{c}, {table}.{c})" for c in cols if c != key
        )
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        sql += f" ON CONFLICT({key}) DO UPDATE SET {updates}" if updates else " ON CONFLICT DO NOTHING"
        conn.execute(sql, [row[c] for c in cols])


# ---------------------------------------------------------------------------
# Réponses brutes et avancement de l'import
# ---------------------------------------------------------------------------

def save_raw(
    conn: sqlite3.Connection,
    fetcher: str,
    start: str,
    end: str,
    outcome: str,
    payload: Any = None,
    http_status: int | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO raw_response (fetcher, start_date, end_date, fetched_at, outcome,
                                     http_status, payload, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(fetcher, start_date, end_date) DO UPDATE SET
               fetched_at = excluded.fetched_at, outcome = excluded.outcome,
               http_status = excluded.http_status, payload = excluded.payload,
               error = excluded.error""",
        (
            fetcher, start, end, utcnow(), outcome, http_status,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            error,
        ),
    )


def get_progress(conn: sqlite3.Connection, fetcher: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM import_progress WHERE fetcher = ?", (fetcher,))
    return {r["start_date"]: r for r in rows}


def mark_progress(
    conn: sqlite3.Connection,
    fetcher: str,
    start: str,
    end: str,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO import_progress (fetcher, start_date, end_date, status, attempts,
                                        last_error, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?)
           ON CONFLICT(fetcher, start_date) DO UPDATE SET
               end_date = excluded.end_date, status = excluded.status,
               attempts = import_progress.attempts + 1,
               last_error = excluded.last_error, updated_at = excluded.updated_at""",
        (fetcher, start, end, status, error, utcnow()),
    )


def progress_summary(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM import_progress GROUP BY status")
    return {r["status"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# Disponibilité des indicateurs
# ---------------------------------------------------------------------------

def touch_availability(conn: sqlite3.Connection, metric: str, dates_with_data: list[str]) -> None:
    """Met à jour la disponibilité : first/last_seen ne bougent que s'il y a des données."""
    first = min(dates_with_data) if dates_with_data else None
    last = max(dates_with_data) if dates_with_data else None
    conn.execute(
        """INSERT INTO metric_availability (metric, first_seen, last_seen, last_checked)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(metric) DO UPDATE SET
               first_seen = CASE WHEN excluded.first_seen IS NULL THEN first_seen
                                 WHEN first_seen IS NULL OR excluded.first_seen < first_seen
                                 THEN excluded.first_seen ELSE first_seen END,
               last_seen  = CASE WHEN excluded.last_seen IS NULL THEN last_seen
                                 WHEN last_seen IS NULL OR excluded.last_seen > last_seen
                                 THEN excluded.last_seen ELSE last_seen END,
               last_checked = excluded.last_checked""",
        (metric, first, last, utcnow()),
    )


def data_overview(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Pour chaque indicateur : nombre de jours, première/dernière date, disponibilité."""
    avail = {r["metric"]: r for r in conn.execute("SELECT * FROM metric_availability")}
    result = []
    for m in METRICS:
        stats = conn.execute(f"SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last FROM {m.table}").fetchone()
        a = avail.get(m.table)
        if a is None:
            state = "unknown"          # jamais interrogé
        elif a["last_seen"] is None:
            state = "not_provided"     # interrogé, jamais de valeur : montre non compatible
        else:
            state = "available"
        result.append({
            "metric": m.table, "label": m.label, "rows": stats["n"],
            "first_date": stats["first"], "last_date": stats["last"], "state": state,
        })
    return result


# ---------------------------------------------------------------------------
# Paramètres (non secrets)
# ---------------------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row and row["value"] is not None else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO app_setting (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM app_setting WHERE key = ?", (key,))


# ---------------------------------------------------------------------------
# Journal des synchronisations
# ---------------------------------------------------------------------------

def start_run(conn: sqlite3.Connection, kind: str, trigger: str) -> int:
    cur = conn.execute(
        "INSERT INTO sync_run (kind, trigger, started_at, status) VALUES (?, ?, ?, 'running')",
        (kind, trigger, utcnow()),
    )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    days: int,
    calls: int,
    errors: int,
    message: str | None = None,
) -> None:
    conn.execute(
        """UPDATE sync_run SET ended_at = ?, status = ?, days_processed = ?, api_calls = ?,
                               errors_count = ?, message = ? WHERE id = ?""",
        (utcnow(), status, days, calls, errors, message, run_id),
    )


def add_run_error(conn: sqlite3.Connection, run_id: int, fetcher: str, date: str, message: str) -> None:
    conn.execute(
        "INSERT INTO sync_error (sync_run_id, fetcher, date, message, at) VALUES (?, ?, ?, ?, ?)",
        (run_id, fetcher, date, message[:1000], utcnow()),
    )


def mark_stale_runs_interrupted(conn: sqlite3.Connection) -> None:
    """Au démarrage : un run resté 'running' a été coupé par l'arrêt de l'application."""
    conn.execute(
        "UPDATE sync_run SET status = 'interrupted', ended_at = COALESCE(ended_at, ?), "
        "message = COALESCE(message, 'Application arrêtée pendant la synchronisation') "
        "WHERE status = 'running'",
        (utcnow(),),
    )


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    runs = [dict(r) for r in conn.execute("SELECT * FROM sync_run ORDER BY id DESC LIMIT ?", (limit,))]
    for run in runs:
        run["errors"] = [
            dict(e) for e in conn.execute(
                "SELECT fetcher, date, message, at FROM sync_error WHERE sync_run_id = ? "
                "ORDER BY id LIMIT 100", (run["id"],)
            )
        ]
    return runs


def last_successful_run(conn: sqlite3.Connection, kind: str = "incremental") -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sync_run WHERE kind = ? AND status IN ('success', 'partial') "
        "ORDER BY id DESC LIMIT 1", (kind,),
    ).fetchone()
