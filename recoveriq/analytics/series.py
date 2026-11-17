"""Séries temporelles : chargement, moyennes mobiles, ligne de base et bande de normalité.

Conventions :

* les séries sont réindexées au jour : un jour sans mesure vaut NaN (jamais 0) ;
* moyenne mobile 7 j / 28 j : au moins 3 / 10 valeurs présentes dans la fenêtre ;
* **ligne de base** d'un jour J = moyenne des 30 jours *précédents* (J exclu), au moins
  10 valeurs ; la bande de normalité vaut ligne de base ± 1 écart type. Exclure J évite
  qu'une valeur anormale tire sa propre référence vers elle.
* les calculs glissants portent sur tout l'historique, puis on coupe à la période
  demandée : les premiers jours d'une période ont donc une ligne de base complète.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from recoveriq.analytics.catalog import PERIODS, SERIES_BY_KEY, Series

BASELINE_DAYS = 30
BASELINE_MIN_VALUES = 10


def load(conn: sqlite3.Connection, series: Series) -> pd.Series:
    """Valeurs d'une série, en unité d'affichage, indexées par date (sans réindexation)."""
    rows = conn.execute(
        f"SELECT date, {series.column} AS v FROM {series.table} "
        f"WHERE {series.column} IS NOT NULL ORDER BY date"
    ).fetchall()
    if not rows:
        return pd.Series(dtype="float64", name=series.key)
    idx = pd.to_datetime([r["date"] for r in rows])
    return pd.Series([float(r["v"]) * series.scale for r in rows], index=idx, name=series.key)


def load_frame(conn: sqlite3.Connection, keys: list[str], start: date | None = None,
               end: date | None = None) -> pd.DataFrame:
    """Plusieurs séries alignées sur un index journalier continu."""
    data = {k: load(conn, SERIES_BY_KEY[k]) for k in keys}
    non_empty = [s for s in data.values() if not s.empty]
    if not non_empty:
        return pd.DataFrame(columns=keys, dtype="float64")
    first = min(s.index.min() for s in non_empty)
    last = max(s.index.max() for s in non_empty)
    if start:
        first = max(first, pd.Timestamp(start))
    if end:
        last = pd.Timestamp(end)
    index = pd.date_range(first, last, freq="D")
    return pd.DataFrame({k: s.reindex(index) for k, s in data.items()}, index=index)


def daily(values: pd.Series, end: date) -> pd.Series:
    """Réindexe au jour, du premier point jusqu'à ``end`` inclus."""
    if values.empty:
        return values
    index = pd.date_range(values.index.min(), pd.Timestamp(end), freq="D")
    return values.reindex(index)


def with_indicators(values: pd.Series) -> pd.DataFrame:
    """Ajoute moyennes mobiles, ligne de base glissante et bande de normalité."""
    prior = values.shift(1)
    base_mean = prior.rolling(BASELINE_DAYS, min_periods=BASELINE_MIN_VALUES).mean()
    base_std = prior.rolling(BASELINE_DAYS, min_periods=BASELINE_MIN_VALUES).std()
    return pd.DataFrame({
        "value": values,
        "ma7": values.rolling(7, min_periods=3).mean(),
        "ma28": values.rolling(28, min_periods=10).mean(),
        "baseline": base_mean,
        "band_low": base_mean - base_std,
        "band_high": base_mean + base_std,
    })


def period_start(period: str, today: date) -> date | None:
    if period not in PERIODS:
        raise ValueError(f"Période inconnue : {period}")
    days = PERIODS[period]
    return today - timedelta(days=days - 1) if days else None


def clean(value: Any, decimals: int | None = None) -> Any:
    """Convertit NaN / numpy en types JSON."""
    if value is None:
        return None
    if isinstance(value, (np.floating, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(float(value), decimals) if decimals is not None else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def trend_per_week(values: pd.Series) -> float | None:
    """Pente de la régression linéaire, en unité par semaine (au moins 7 points)."""
    v = values.dropna()
    if len(v) < 7:
        return None
    x = (v.index - v.index[0]).days.to_numpy(dtype=float)
    if np.ptp(x) == 0:
        return None
    slope = np.polyfit(x, v.to_numpy(dtype=float), 1)[0]
    return float(slope * 7)


def series_view(conn: sqlite3.Connection, key: str, period: str, today: date) -> dict[str, Any]:
    """Données complètes de la vue « indicateur »."""
    s = SERIES_BY_KEY[key]
    raw = load(conn, s)
    meta = {
        "key": s.key, "label": s.label, "unit": s.unit, "group": s.group,
        "higher_is_better": s.higher_is_better, "decimals": s.decimals,
    }
    if raw.empty:
        return {"meta": meta, "available": False, "points": [], "stats": None}

    frame = with_indicators(daily(raw, today))
    start = period_start(period, today)
    if start:
        frame = frame[frame.index >= pd.Timestamp(start)]
    # Rogner les jours vides en tête de période (avant la première mesure).
    first_valid = frame["value"].first_valid_index()
    if first_valid is not None:
        frame = frame[frame.index >= first_valid]

    d = s.decimals + 1
    points = [
        {"date": idx.date().isoformat(), **{col: clean(row[col], d) for col in frame.columns}}
        for idx, row in frame.iterrows()
    ]
    v = frame["value"].dropna()
    last_idx = raw.index.max()
    stats = {
        "n": int(v.size),
        "latest": clean(raw.iloc[-1], d),
        "latest_date": last_idx.date().isoformat(),
        "mean": clean(v.mean(), d),
        "std": clean(v.std(), d),
        "min": clean(v.min(), d),
        "max": clean(v.max(), d),
        "trend_per_week": clean(trend_per_week(v), d + 1),
    }
    from recoveriq.analytics.zones import zones_for   # import local : zones → training → series

    zones = zones_for(conn, key, [pt["date"] for pt in points])
    return {"meta": meta, "available": True, "points": points, "stats": stats, "zones": zones}


def compare_to_baseline(values: pd.Series, at: pd.Timestamp, higher_is_better: bool | None) -> dict[str, Any]:
    """Valeur du jour ``at`` comparée aux 30 jours précédents."""
    window = values[(values.index < at) & (values.index >= at - pd.Timedelta(days=BASELINE_DAYS))].dropna()
    value = values.get(at)
    result: dict[str, Any] = {"baseline": None, "std": None, "delta": None, "delta_pct": None,
                              "z": None, "status": "insufficient", "favorable": None}
    if value is None or pd.isna(value) or len(window) < BASELINE_MIN_VALUES:
        return result
    mean, std = float(window.mean()), float(window.std())
    delta = float(value) - mean
    if std > 0:
        z: float | None = delta / std
        is_normal = abs(z) < 1
    else:  # ligne de base constante : tout écart est hors de la bande (vide)
        z, is_normal = None, delta == 0
    status = "normal" if is_normal else ("above" if delta > 0 else "below")
    favorable = None
    if status != "normal" and higher_is_better is not None:
        favorable = (status == "above") == higher_is_better
    result.update(baseline=mean, std=std, delta=delta, z=z, status=status, favorable=favorable,
                  delta_pct=(delta / mean * 100) if mean else None)
    return result
