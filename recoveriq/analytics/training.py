"""Vue charge d'entraînement : aiguë vs chronique, ratio et zones, focus, volume."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd

from recoveriq.analytics.series import clean, period_start

# Zones du ratio aiguë / chronique (ACWR), d'après Gabbett (2016) :
# 0,8 – 1,3 = « zone optimale » ; au-delà de 1,5, le risque de blessure augmente nettement.
ACWR_ZONES: tuple[dict[str, Any], ...] = (
    {"id": "under", "label": "Sous-charge", "min": 0.0, "max": 0.8},
    {"id": "optimal", "label": "Optimal", "min": 0.8, "max": 1.3},
    {"id": "caution", "label": "Vigilance", "min": 1.3, "max": 1.5},
    {"id": "risk", "label": "Risque", "min": 1.5, "max": None},
)

_LOAD_COLUMNS = (
    "acute_load", "chronic_load", "chronic_min", "chronic_max", "acwr", "acwr_status",
    "focus_low_aerobic", "focus_high_aerobic", "focus_anaerobic",
    "focus_low_aerobic_min", "focus_low_aerobic_max", "focus_high_aerobic_min",
    "focus_high_aerobic_max", "focus_anaerobic_min", "focus_anaerobic_max", "focus_feedback",
)


def acwr_zone(value: float | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    for zone in ACWR_ZONES:
        if zone["max"] is None or value < zone["max"]:
            return zone["id"]
    return None


def _where_period(start: date | None) -> tuple[str, tuple]:
    return ("WHERE date >= ?", (start.isoformat(),)) if start else ("", ())


def training_view(conn: sqlite3.Connection, period: str, today: date) -> dict[str, Any]:
    start = period_start(period, today)
    where, params = _where_period(start)

    rows = [dict(r) for r in conn.execute(
        f"SELECT date, {', '.join(_LOAD_COLUMNS)} FROM daily_training_load {where} ORDER BY date", params)]
    for r in rows:
        r["zone"] = acwr_zone(r["acwr"])

    zone_days = {z["id"]: 0 for z in ACWR_ZONES}
    for r in rows:
        if r["zone"]:
            zone_days[r["zone"]] += 1

    latest_focus = next((r for r in reversed(rows) if r["focus_low_aerobic"] is not None), None)
    focus = None
    if latest_focus:
        focus = {
            "date": latest_focus["date"],
            "feedback": latest_focus["focus_feedback"],
            "items": [
                {"id": key, "label": label, "value": latest_focus[f"focus_{key}"],
                 "min": latest_focus[f"focus_{key}_min"], "max": latest_focus[f"focus_{key}_max"]}
                for key, label in (("low_aerobic", "Aérobie basse"), ("high_aerobic", "Aérobie haute"),
                                   ("anaerobic", "Anaérobie"))
            ],
        }

    status_rows = conn.execute(
        f"SELECT date, status_phrase FROM daily_training_status {where} ORDER BY date", params).fetchall()
    # Ne garder que les changements de statut (frise).
    timeline, previous = [], object()
    for r in status_rows:
        if r["status_phrase"] != previous:
            timeline.append({"date": r["date"], "status": r["status_phrase"]})
            previous = r["status_phrase"]

    return {
        "zones": ACWR_ZONES,
        "daily": rows,
        "zone_days": zone_days,
        "focus": focus,
        "status_timeline": timeline,
        "current_status": timeline[-1] if timeline else None,
        "weekly_volume": weekly_volume(conn, start),
    }


def weekly_volume(conn: sqlite3.Connection, start: date | None) -> list[dict[str, Any]]:
    """Volume hebdomadaire (semaines ISO, lundi) à partir des activités."""
    where, params = _where_period(start)
    df = pd.read_sql_query(
        f"SELECT date, duration_s, distance_m, elev_gain_m, training_load FROM activity {where}",
        conn, params=params, parse_dates=["date"])
    if df.empty:
        return []
    df["week"] = df["date"].dt.to_period("W-SUN").dt.start_time
    agg = df.groupby("week").agg(
        activities=("date", "size"),
        hours=("duration_s", lambda s: s.sum() / 3600),
        distance_km=("distance_m", lambda s: s.sum() / 1000),
        elevation_m=("elev_gain_m", "sum"),
        load=("training_load", "sum"),
    ).reset_index()
    return [
        {"week": r.week.date().isoformat(), "activities": int(r.activities),
         "hours": clean(r.hours, 2), "distance_km": clean(r.distance_km, 1),
         "elevation_m": clean(r.elevation_m, 0), "load": clean(r.load, 0)}
        for r in agg.itertuples()
    ]


def activities_list(conn: sqlite3.Connection, period: str, today: date) -> list[dict[str, Any]]:
    where, params = _where_period(period_start(period, today))
    return [dict(r) for r in conn.execute(
        f"WITH a AS ({_ACTIVITY_WINDOW}) "
        f"SELECT activity_id, date, start_local, type, name, duration_s, moving_s, distance_m, elev_gain_m, "
        f"elev_loss_m, avg_hr, max_hr, calories, training_load, aerobic_te, anaerobic_te, vo2max, "
        f"best_1k_s, best_5k_s, best_10k_s, ({_RECOVERY_AFTER}) AS recovery_time_min "
        f"FROM a {where} ORDER BY start_local DESC", params)]


# Fin de chaque activité et début de la suivante (sur tout l'historique, avant filtrage).
_ACTIVITY_WINDOW = (
    "SELECT *, datetime(start_local, '+' || CAST(COALESCE(duration_s, 0) AS INTEGER) || ' seconds') AS end_local, "
    "LEAD(start_local) OVER (ORDER BY start_local) AS next_start FROM activity"
)

# Durée de récupération après l'effort : Garmin crée un relevé Training Readiness
# AFTER_POST_EXERCISE_RESET quelques secondes après l'enregistrement de l'activité.
# On prend le premier relevé de ce type après le début, au plus 3 h après la fin
# (la durée exclut les pauses, au ski par exemple) et avant l'activité suivante.
_RECOVERY_AFTER = (
    "SELECT e.recovery_time_min FROM readiness_event e "
    "WHERE e.context = 'AFTER_POST_EXERCISE_RESET' AND e.timestamp_local >= a.start_local "
    "AND e.timestamp_local <= datetime(a.end_local, '+3 hours') "
    "AND (a.next_start IS NULL OR e.timestamp_local < a.next_start) "
    "ORDER BY e.timestamp_local LIMIT 1"
)
