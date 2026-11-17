"""Archivage des rapports IA (tables ``ai_report`` et ``ai_provider_result``,
créées par ``db/migration_002_ai.sql``)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from recoveriq.db.repository import utcnow



def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def create_report(conn: sqlite3.Connection, trigger: str, start: str, end: str, days: int) -> int:
    cur = conn.execute(
        "INSERT INTO ai_report (created_at, trigger, period_start, period_end, period_days, status) "
        "VALUES (?, ?, ?, ?, ?, 'running')", (utcnow(), trigger, start, end, days))
    return int(cur.lastrowid)


def save_summary(conn: sqlite3.Connection, report_id: int, summary: dict[str, Any]) -> None:
    conn.execute("UPDATE ai_report SET summary_json = ? WHERE id = ?",
                 (json.dumps(summary, ensure_ascii=False), report_id))


def save_result(conn: sqlite3.Connection, report_id: int, r: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ai_provider_result (report_id, provider, model, status, duration_ms, "
        "input_tokens, output_tokens, cost, report_json, warnings, raw_text, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (report_id, r["provider"], r.get("model"), r["status"], r.get("duration_ms"), r.get("input_tokens"),
         r.get("output_tokens"), r.get("cost"),
         json.dumps(r["report"], ensure_ascii=False) if r.get("report") else None,
         json.dumps(r.get("warnings") or [], ensure_ascii=False), r.get("raw_text"), r.get("error")))


def finish_report(conn: sqlite3.Connection, report_id: int, **fields: Any) -> None:
    for key in ("comparison", "synthesis"):
        if key in fields:
            value = fields.pop(key)
            fields[f"{key}_json"] = json.dumps(value, ensure_ascii=False) if value is not None else None
    fields["finished_at"] = utcnow()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE ai_report SET {cols} WHERE id = ?", (*fields.values(), report_id))


def mark_stale_running(conn: sqlite3.Connection) -> None:
    """Au démarrage : une analyse « en cours » a été interrompue par l'arrêt de l'appli."""
    conn.execute("UPDATE ai_report SET status = 'failed', error = 'interrompue (arrêt de l''application)', "
                 "finished_at = ? WHERE status = 'running'", (utcnow(),))


def list_reports(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, created_at, finished_at, trigger, period_start, period_end, period_days, status, "
        "synthesis_mode, aggregator, total_cost, cost_complete, error FROM ai_report "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    results = conn.execute(
        "SELECT report_id, provider, model, status FROM ai_provider_result WHERE report_id IN "
        f"(SELECT id FROM ai_report ORDER BY id DESC LIMIT ?)", (limit,)).fetchall()
    by_report: dict[int, list[dict[str, Any]]] = {}
    for r in results:
        by_report.setdefault(r["report_id"], []).append(
            {"provider": r["provider"], "model": r["model"], "status": r["status"]})
    return [{**dict(r), "providers": by_report.get(r["id"], [])} for r in rows]


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM ai_report WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    for key in ("summary", "comparison", "synthesis"):
        out[key] = _loads(out.pop(f"{key}_json"))
    out["results"] = [
        {**{k: r[k] for k in r.keys() if k not in ("report_json", "warnings")},
         "report": _loads(r["report_json"]), "warnings": _loads(r["warnings"]) or []}
        for r in conn.execute("SELECT * FROM ai_provider_result WHERE report_id = ? ORDER BY rowid",
                              (report_id,))
    ]
    return out


def delete_report(conn: sqlite3.Connection, report_id: int) -> bool:
    return conn.execute("DELETE FROM ai_report WHERE id = ?", (report_id,)).rowcount > 0


def last_report_at(conn: sqlite3.Connection, trigger: str) -> str | None:
    row = conn.execute("SELECT MAX(created_at) AS at FROM ai_report WHERE trigger = ? AND status != 'failed'",
                       (trigger,)).fetchone()
    return row["at"] if row else None
