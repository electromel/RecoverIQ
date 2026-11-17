"""Résumé agrégé envoyé aux LLM.

**Seules des statistiques agrégées sortent de la machine** : pour chaque indicateur,
moyenne, extrêmes, écart type, tendance et comparaison à une période de référence ;
pour l'entraînement, des totaux et des répartitions. Aucune valeur journalière,
aucune date d'activité individuelle, aucun identifiant (nom, e-mail, appareil).

Le résumé est aussi archivé avec chaque rapport et consultable dans l'appli :
l'utilisateur voit exactement ce qui a été transmis.

Période analysée : ``days`` jours se terminant à ``end`` (inclus).
Période de référence : les ``ref_days`` jours précédents, avec
``ref_days = clamp(4 × days, 28, 365)``. Un indicateur est « au-dessus » /
« en dessous » quand la moyenne de la période s'écarte de plus d'un écart type
(journalier) de la moyenne de référence.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

import pandas as pd

from recoveriq.analytics.catalog import SERIES
from recoveriq.analytics.correlations import PAIRS, correlate
from recoveriq.analytics.series import clean, load, load_frame, trend_per_week
from recoveriq.analytics.training import ACWR_ZONES, acwr_zone

SUMMARY_VERSION = 1
MIN_REF_VALUES = 7
CORRELATION_MIN_DAYS = 28


def reference_days(days: int) -> int:
    return max(28, min(365, 4 * days))


def _window(values: pd.Series, start: date, end: date) -> pd.Series:
    return values[(values.index >= pd.Timestamp(start)) & (values.index <= pd.Timestamp(end))]


def _metric_summary(conn: sqlite3.Connection, s, start: date, end: date, ref_start: date) -> dict[str, Any] | None:
    raw = load(conn, s)
    if raw.empty:
        return None
    period = _window(raw, start, end).dropna()
    if period.empty:
        return None
    ref = _window(raw, ref_start, start - timedelta(days=1)).dropna()
    d = s.decimals + 1
    out: dict[str, Any] = {
        "key": s.key, "label": s.label, "unit": s.unit, "group": s.group,
        "higher_is_better": s.higher_is_better,
        "days_with_data": int(period.size),
        "mean": clean(period.mean(), d), "min": clean(period.min(), d), "max": clean(period.max(), d),
        "std": clean(period.std(), d) if period.size > 1 else None,
        "trend_per_week": clean(trend_per_week(period), d + 1),
        "last": clean(period.iloc[-1], d),
        "reference": None,
    }
    if ref.size >= MIN_REF_VALUES:
        ref_mean, ref_std = float(ref.mean()), float(ref.std())
        delta = float(period.mean()) - ref_mean
        z = delta / ref_std if ref_std > 0 else None
        status = "normal" if z is None or abs(z) < 1 else ("above" if delta > 0 else "below")
        out["reference"] = {
            "mean": clean(ref_mean, d), "std": clean(ref_std, d), "days_with_data": int(ref.size),
            "delta": clean(delta, d), "delta_pct": clean(delta / ref_mean * 100, 1) if ref_mean else None,
            "z": clean(z, 2), "status": status,
        }
    return out


def _training(conn: sqlite3.Connection, start: date, end: date) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT date, acute_load, chronic_load, acwr, focus_feedback FROM daily_training_load "
        "WHERE date BETWEEN ? AND ? ORDER BY date", (start.isoformat(), end.isoformat())).fetchall()
    statuses = conn.execute(
        "SELECT status_phrase FROM daily_training_status WHERE date BETWEEN ? AND ? "
        "AND status_phrase IS NOT NULL ORDER BY date", (start.isoformat(), end.isoformat())).fetchall()
    if not rows and not statuses:
        return None
    acwr = [r["acwr"] for r in rows if r["acwr"] is not None]
    zone_days = {z["id"]: 0 for z in ACWR_ZONES}
    for v in acwr:
        zone_days[acwr_zone(v)] += 1
    latest = next((r for r in reversed(rows) if r["acwr"] is not None), None)
    # Suite des statuts successifs (sans répétition), sans dates.
    sequence: list[str] = []
    for r in statuses:
        if not sequence or sequence[-1] != r["status_phrase"]:
            sequence.append(r["status_phrase"])
    feedback = next((r["focus_feedback"] for r in reversed(rows) if r["focus_feedback"]), None)
    return {
        "acwr_zones": {z["id"]: {"label": z["label"], "min": z["min"], "max": z["max"]} for z in ACWR_ZONES},
        "acwr_last": clean(latest["acwr"], 2) if latest else None,
        "acwr_last_zone": acwr_zone(latest["acwr"]) if latest else None,
        "acwr_mean": clean(sum(acwr) / len(acwr), 2) if acwr else None,
        "days_per_acwr_zone": zone_days,
        "acute_load_last": clean(latest["acute_load"], 0) if latest else None,
        "chronic_load_last": clean(latest["chronic_load"], 0) if latest else None,
        "training_status_sequence": sequence[-6:],
        "load_focus_feedback": feedback,
    }


def _activities(conn: sqlite3.Connection, start: date, end: date, ref_start: date, days: int,
                ref_days: int) -> dict[str, Any]:
    def totals(a: date, b: date) -> sqlite3.Row:
        return conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(duration_s), 0) / 3600.0 AS hours, "
            "COALESCE(SUM(distance_m), 0) / 1000.0 AS km, COALESCE(SUM(elev_gain_m), 0) AS elev, "
            "COALESCE(SUM(training_load), 0) AS load FROM activity WHERE date BETWEEN ? AND ?",
            (a.isoformat(), b.isoformat())).fetchone()

    cur = totals(start, end)
    ref = totals(ref_start, start - timedelta(days=1))
    by_type = conn.execute(
        "SELECT type, COUNT(*) AS n, SUM(duration_s) / 3600.0 AS hours FROM activity "
        "WHERE date BETWEEN ? AND ? GROUP BY type ORDER BY hours DESC LIMIT 8",
        (start.isoformat(), end.isoformat())).fetchall()
    per_week = lambda value, span: clean(value * 7 / span, 2)  # noqa: E731
    return {
        "count": cur["n"], "hours": clean(cur["hours"], 1), "distance_km": clean(cur["km"], 1),
        "elevation_gain_m": clean(cur["elev"], 0), "training_load_total": clean(cur["load"], 0),
        "hours_per_week": per_week(cur["hours"], days),
        "reference_hours_per_week": per_week(ref["hours"], ref_days),
        "reference_count_per_week": per_week(ref["n"], ref_days),
        "by_type": [{"type": r["type"] or "other", "count": r["n"], "hours": clean(r["hours"], 1)}
                    for r in by_type],
    }


def _correlations(conn: sqlite3.Connection, start: date, end: date) -> list[dict[str, Any]]:
    keys = sorted({p.x for p in PAIRS} | {p.y for p in PAIRS})
    frame = load_frame(conn, keys, start=start, end=end)
    out = []
    for p in PAIRS:
        if p.x not in frame or p.y not in frame:
            continue
        st = correlate(frame[p.x], frame[p.y].shift(-p.lag_days))
        if st["sufficient"]:
            out.append({"x": p.x, "y": p.y, "lag_days": p.lag_days, "description": p.note, "n": st["n"],
                        "pearson_r": st["pearson_r"], "p_value": st["pearson_p"], "strength": st["strength"]})
    return out


def build_summary(conn: sqlite3.Connection, end: date, days: int) -> dict[str, Any]:
    start = end - timedelta(days=days - 1)
    ref_days = reference_days(days)
    ref_start = start - timedelta(days=ref_days)

    metrics, missing = [], []
    for s in SERIES:
        m = _metric_summary(conn, s, start, end, ref_start)
        if m is None:
            missing.append(s.key)
        else:
            metrics.append(m)

    return {
        "summary_version": SUMMARY_VERSION,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "reference_period": {"start": ref_start.isoformat(),
                             "end": (start - timedelta(days=1)).isoformat(), "days": ref_days},
        "conventions": {
            "sleep_dating": "les nuits sont datées du jour du réveil",
            "status": "above/below = moyenne de la période à plus d'un écart type de la référence",
            "trend_per_week": "pente de régression linéaire, en unité par semaine",
        },
        "metrics": metrics,
        "missing_metrics": missing,
        "training": _training(conn, start, end),
        "activities": _activities(conn, start, end, ref_start, days, ref_days),
        "correlations": _correlations(conn, start, end) if days >= CORRELATION_MIN_DAYS else [],
    }
