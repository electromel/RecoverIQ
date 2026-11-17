"""Page d'accueil : cartes du jour comparées à la ligne de base sur 30 jours."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from recoveriq.analytics.catalog import SERIES_BY_KEY
from recoveriq.analytics.series import clean, compare_to_baseline, daily, load

# Une valeur « du jour » peut dater de la veille (ex. sommeil pas encore synchronisé).
MAX_AGE_DAYS = 2
SPARKLINE_DAYS = 14


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    main: str                  # clé de série principale
    secondary: tuple[str, ...] = ()


CARDS: tuple[Card, ...] = (
    Card("body_battery", "Body Battery", "bb_at_wake", ("bb_highest", "bb_charged", "bb_sleep_charge")),
    Card("hrv", "VFC", "hrv", ("hrv_weekly", "rhr")),
    Card("readiness", "Training Readiness", "readiness", ("recovery_time",)),
    Card("sleep", "Sommeil", "sleep_score", ("sleep_duration", "sleep_deep", "sleep_rem")),
    Card("stress", "Stress", "stress_avg", ("stress_high", "stress_rest")),
)


def _metric(conn: sqlite3.Connection, key: str, today: date, sparkline: bool) -> dict[str, Any]:
    s = SERIES_BY_KEY[key]
    raw = load(conn, s)
    out: dict[str, Any] = {"key": key, "label": s.label, "unit": s.unit, "decimals": s.decimals,
                           "value": None, "date": None, "stale": False}
    if raw.empty:
        out["available"] = False
        return out
    out["available"] = True
    values = daily(raw, today)
    last = raw.index.max()
    age = (pd.Timestamp(today) - last).days
    out.update(value=clean(raw.iloc[-1], s.decimals + 1), date=last.date().isoformat(), stale=age > MAX_AGE_DAYS)
    cmp = compare_to_baseline(values, last, s.higher_is_better)
    out["comparison"] = {k: clean(v, s.decimals + 2) if isinstance(v, float) else v for k, v in cmp.items()}
    if sparkline:
        recent = values[values.index > pd.Timestamp(today) - pd.Timedelta(days=SPARKLINE_DAYS)]
        out["sparkline"] = [clean(v, s.decimals + 1) for v in recent]
    return out


def home_view(conn: sqlite3.Connection, today: date) -> dict[str, Any]:
    cards = []
    for card in CARDS:
        cards.append({
            "id": card.id,
            "title": card.title,
            "main": _metric(conn, card.main, today, sparkline=True),
            "secondary": [_metric(conn, k, today, sparkline=False) for k in card.secondary],
        })

    status = conn.execute(
        "SELECT s.date, s.status_phrase, l.acwr, l.acwr_status, l.acute_load, l.chronic_load "
        "FROM daily_training_status s LEFT JOIN daily_training_load l USING (date) "
        "ORDER BY s.date DESC LIMIT 1"
    ).fetchone()
    return {"today": today.isoformat(), "cards": cards,
            "training": dict(status) if status else None}
