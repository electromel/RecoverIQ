"""Vue corrélations.

Alignement temporel (important pour l'interprétation) :

* les données de sommeil sont datées du **jour du réveil** : la « nuit du jour J » est
  la nuit qui se termine le matin de J ;
* « sommeil → VFC / Body Battery du lendemain » : nuit se terminant en J vs VFC
  nocturne et Body Battery au réveil de J (mesures prises à la fin de cette même nuit) ;
* « stress de la journée → recharge nocturne » : stress moyen de J vs recharge
  pendant la nuit suivante, donc datée de J+1.

Une corrélation n'est calculée qu'à partir de ``MIN_PAIRS`` couples de valeurs, et
n'établit jamais de lien de cause à effet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from recoveriq.analytics.catalog import SERIES_BY_KEY
from recoveriq.analytics.series import clean, load, load_frame, period_start

MIN_PAIRS = 10
VO2_VOLUME_WEEKS = 4


@dataclass(frozen=True)
class Pair:
    id: str
    group: str
    x: str                 # clé de série
    y: str
    lag_days: int = 0      # y est pris à J + lag_days
    note: str = ""


PAIRS: tuple[Pair, ...] = (
    Pair("sleep_score_hrv", "sleep_next_day", "sleep_score", "hrv", 0, "Nuit se terminant en J → VFC de cette nuit"),
    Pair("sleep_duration_hrv", "sleep_next_day", "sleep_duration", "hrv", 0, "Nuit se terminant en J → VFC de cette nuit"),
    Pair("sleep_score_bb", "sleep_next_day", "sleep_score", "bb_at_wake", 0, "Nuit se terminant en J → Body Battery au réveil"),
    Pair("sleep_duration_bb", "sleep_next_day", "sleep_duration", "bb_at_wake", 0, "Nuit se terminant en J → Body Battery au réveil"),
    Pair("sleep_deep_hrv", "sleep_next_day", "sleep_deep", "hrv", 0, "Sommeil profond → VFC de la nuit"),
    Pair("stress_recharge", "stress_night", "stress_avg", "bb_sleep_charge", 1, "Stress moyen de J → recharge pendant la nuit suivante"),
    Pair("stress_high_recharge", "stress_night", "stress_high", "bb_sleep_charge", 1, "Stress élevé de J → recharge pendant la nuit suivante"),
    Pair("stress_hrv", "stress_night", "stress_avg", "hrv", 1, "Stress moyen de J → VFC de la nuit suivante"),
)

GROUPS = {
    "sleep_next_day": "Sommeil de la nuit → VFC et Body Battery du lendemain",
    "stress_night": "Stress de la journée → récupération la nuit suivante",
    "vo2_volume": "VO2 max et volume d'entraînement",
    "weekday_weekend": "Semaine / week-end",
}

WEEKDAY_METRICS = ("sleep_duration", "sleep_score", "hrv", "rhr", "bb_at_wake", "bb_charged",
                   "stress_avg", "intensity", "readiness")


def strength_label(r: float | None) -> str:
    if r is None:
        return "—"
    a = abs(r)
    if a < 0.1:
        return "négligeable"
    sense = "positive" if r > 0 else "négative"
    if a < 0.3:
        return f"faible {sense}"
    if a < 0.5:
        return f"modérée {sense}"
    return f"forte {sense}"


def correlate(x: pd.Series, y: pd.Series) -> dict[str, Any]:
    """Pearson + Spearman sur les couples complets, avec droite de régression."""
    mask = x.notna() & y.notna()
    xs, ys = x[mask].to_numpy(dtype=float), y[mask].to_numpy(dtype=float)
    n = int(mask.sum())
    result: dict[str, Any] = {"n": n, "pearson_r": None, "pearson_p": None, "spearman_rho": None,
                              "spearman_p": None, "slope": None, "intercept": None,
                              "strength": "—", "sufficient": n >= MIN_PAIRS}
    if n < MIN_PAIRS or np.ptp(xs) == 0 or np.ptp(ys) == 0:
        result["sufficient"] = False
        return result
    pr = stats.pearsonr(xs, ys)
    sr = stats.spearmanr(xs, ys)
    slope, intercept = np.polyfit(xs, ys, 1)
    result.update(
        pearson_r=clean(pr.statistic, 3), pearson_p=clean(pr.pvalue, 4),
        spearman_rho=clean(sr.statistic, 3), spearman_p=clean(sr.pvalue, 4),
        slope=clean(slope, 4), intercept=clean(intercept, 4),
        strength=strength_label(float(pr.statistic)),
    )
    return result


def _series_meta(key: str) -> dict[str, Any]:
    s = SERIES_BY_KEY[key]
    return {"key": key, "label": s.label, "unit": s.unit}


def correlations_view(conn: sqlite3.Connection, period: str, today: date) -> dict[str, Any]:
    start = period_start(period, today)
    keys = sorted({p.x for p in PAIRS} | {p.y for p in PAIRS} | set(WEEKDAY_METRICS))
    frame = load_frame(conn, keys, end=today)
    if start is not None and not frame.empty:
        frame = frame[frame.index >= pd.Timestamp(start)]

    pairs = []
    for p in PAIRS:
        x = frame[p.x] if p.x in frame else pd.Series(dtype=float)
        y = frame[p.y].shift(-p.lag_days) if p.y in frame else pd.Series(dtype=float)
        mask = x.notna() & y.notna()
        pairs.append({
            "id": p.id, "group": p.group, "note": p.note, "lag_days": p.lag_days,
            "x": _series_meta(p.x), "y": _series_meta(p.y),
            "stats": correlate(x, y),
            "points": [{"date": d.date().isoformat(), "x": clean(xv, 3), "y": clean(yv, 3)}
                       for d, xv, yv in zip(x[mask].index, x[mask], y[mask])],
        })

    return {
        "groups": GROUPS,
        "pairs": pairs,
        "vo2_volume": vo2_vs_volume(conn, start, today),
        "weekday_weekend": weekday_weekend(frame),
        "min_pairs": MIN_PAIRS,
    }


def vo2_vs_volume(conn: sqlite3.Connection, start: date | None, today: date) -> dict[str, Any]:
    """VO2 max (course) en fin de semaine vs volume d'entraînement des 4 semaines précédentes.

    Deux lectures : le niveau de VO2 max, et sa variation sur ces 4 semaines.
    """
    vo2 = load(conn, SERIES_BY_KEY["vo2max"])
    acts = pd.read_sql_query("SELECT date, duration_s, training_load FROM activity", conn, parse_dates=["date"])
    empty = {"points": [], "level": correlate(pd.Series(dtype=float), pd.Series(dtype=float)),
             "change": correlate(pd.Series(dtype=float), pd.Series(dtype=float)), "weeks": VO2_VOLUME_WEEKS}
    if vo2.empty or acts.empty:
        return empty

    weekly_hours = acts.set_index("date")["duration_s"].resample("W-SUN").sum() / 3600
    weekly_load = acts.set_index("date")["training_load"].resample("W-SUN").sum()
    weeks = pd.date_range(min(weekly_hours.index.min(), vo2.index.min()), pd.Timestamp(today), freq="W-SUN")
    hours = weekly_hours.reindex(weeks, fill_value=0.0)
    load_w = weekly_load.reindex(weeks, fill_value=0.0)
    # VO2 max connue en fin de semaine (dernière mesure, propagée car mesurée irrégulièrement).
    vo2_week = vo2.resample("W-SUN").last().reindex(weeks).ffill()

    df = pd.DataFrame({
        "vo2max": vo2_week,
        "hours_4w": hours.rolling(VO2_VOLUME_WEEKS).sum(),
        "load_4w": load_w.rolling(VO2_VOLUME_WEEKS).sum(),
    })
    df["vo2_change_4w"] = df["vo2max"] - df["vo2max"].shift(VO2_VOLUME_WEEKS)
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    df = df.dropna(subset=["vo2max", "hours_4w"])
    return {
        "weeks": VO2_VOLUME_WEEKS,
        "points": [{"week_end": d.date().isoformat(), "vo2max": clean(r.vo2max, 1),
                    "hours_4w": clean(r.hours_4w, 2), "load_4w": clean(r.load_4w, 0),
                    "vo2_change_4w": clean(r.vo2_change_4w, 2)} for d, r in df.iterrows()],
        "level": correlate(df["hours_4w"], df["vo2max"]),
        "change": correlate(df["hours_4w"], df["vo2_change_4w"]),
    }


def weekday_weekend(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Moyennes semaine (lun–ven) vs week-end (sam–dim), test t de Welch.

    Pour le sommeil (daté du réveil), « week-end » = nuits de vendredi et samedi.
    """
    out = []
    if frame.empty:
        return out
    is_weekend = frame.index.day_of_week >= 5
    for key in WEEKDAY_METRICS:
        if key not in frame:
            continue
        s = SERIES_BY_KEY[key]
        wk, we = frame[key][~is_weekend].dropna(), frame[key][is_weekend].dropna()
        row: dict[str, Any] = {**_series_meta(key), "decimals": s.decimals,
                               "weekday_mean": clean(wk.mean(), s.decimals + 1), "weekday_n": int(wk.size),
                               "weekend_mean": clean(we.mean(), s.decimals + 1), "weekend_n": int(we.size),
                               "difference": None, "difference_pct": None, "p_value": None,
                               "cohen_d": None, "significant": False}
        if wk.size >= MIN_PAIRS and we.size >= MIN_PAIRS:
            diff = float(we.mean() - wk.mean())
            pooled = np.sqrt((wk.var() + we.var()) / 2)
            test = stats.ttest_ind(we, wk, equal_var=False)
            row.update(
                difference=clean(diff, s.decimals + 1),
                difference_pct=clean(diff / wk.mean() * 100, 1) if wk.mean() else None,
                p_value=clean(test.pvalue, 4),
                cohen_d=clean(diff / pooled, 2) if pooled > 0 else None,
                significant=bool(test.pvalue < 0.05),
            )
        out.append(row)
    return out
