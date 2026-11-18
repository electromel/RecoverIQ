"""Plages de couleur Garmin affichées en fond des graphiques d'indicateurs.

Chaque plage a un identifiant de couleur (``risk`` rouge, ``caution`` orange,
``optimal`` vert, ``good`` bleu, ``top`` violet, ``under`` gris) et des bornes
``min`` / ``max`` :

* fixes (nombre) : score de sommeil, Training Readiness, stress, Body Battery, ACWR ;
* journalières (liste alignée sur les dates du graphique, ``None`` = pas de plage ce
  jour-là) : VFC (ligne de base personnelle calculée par Garmin chaque jour), VO2 max
  (catégories selon l'âge à la date et le sexe), charge aiguë (plage optimale Garmin),
  âge de forme physique (âge réel à la date).

Une borne ``None`` (hors liste) = bord du graphique.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right
from datetime import date
from typing import Any

from recoveriq.analytics.training import ACWR_ZONES
from recoveriq.db import repository as repo

SETTING_GENDER = "profile.gender"          # MALE | FEMALE
SETTING_BIRTH_DATE = "profile.birth_date"  # YYYY-MM-DD

# VO2 max : seuils bas de « Moyen », « Bon », « Excellent », « Supérieur » par tranche d'âge
# (tableau publié par Garmin, d'après le Cooper Institute). En dessous : « Faible ».
_VO2_AGES = (30, 40, 50, 60, 70)   # bornes hautes exclues des tranches 20-29 … 60-69 ; 70+ ensuite
_VO2_MALE = (
    (41.7, 45.4, 51.1, 55.5),   # 20-29
    (40.5, 44.0, 48.3, 54.1),   # 30-39
    (38.5, 42.4, 46.4, 52.6),   # 40-49
    (35.6, 39.2, 43.4, 49.0),   # 50-59
    (32.3, 35.5, 39.5, 45.8),   # 60-69
    (29.4, 32.3, 36.7, 42.2),   # 70-79
)
_VO2_FEMALE = (
    (36.1, 39.5, 43.9, 49.7),
    (34.4, 37.8, 42.4, 47.5),
    (33.0, 36.3, 39.7, 45.4),
    (30.1, 33.0, 36.7, 41.2),
    (27.5, 30.0, 33.0, 37.9),
    (25.9, 28.1, 30.9, 36.8),
)
_VO2_LEVELS = (("risk", "Faible"), ("caution", "Moyen"), ("optimal", "Bon"),
               ("good", "Excellent"), ("top", "Supérieur"))

_FIXED: dict[str, dict[str, Any]] = {
    "sleep_score": {
        "note": "Plages Garmin du score de sommeil.",
        "items": [
            {"id": "risk", "label": "Médiocre (< 60)", "min": None, "max": 60},
            {"id": "caution", "label": "Passable (60-79)", "min": 60, "max": 80},
            {"id": "optimal", "label": "Bon (80-89)", "min": 80, "max": 90},
            {"id": "good", "label": "Excellent (90-100)", "min": 90, "max": None},
        ],
    },
    "readiness": {
        "note": "Plages Garmin du Training Readiness.",
        "items": [
            {"id": "risk", "label": "Faible (1-24)", "min": None, "max": 25},
            {"id": "caution", "label": "Bas (25-49)", "min": 25, "max": 50},
            {"id": "optimal", "label": "Modéré (50-74)", "min": 50, "max": 75},
            {"id": "good", "label": "Élevé (75-94)", "min": 75, "max": 95},
            {"id": "top", "label": "Optimal (95-100)", "min": 95, "max": None},
        ],
    },
    "stress_avg": {
        "note": "Plages Garmin du niveau de stress.",
        "items": [
            {"id": "good", "label": "Repos (0-25)", "min": None, "max": 26},
            {"id": "optimal", "label": "Faible (26-50)", "min": 26, "max": 51},
            {"id": "caution", "label": "Moyen (51-75)", "min": 51, "max": 76},
            {"id": "risk", "label": "Élevé (76-100)", "min": 76, "max": None},
        ],
    },
    "fitness_trend": {
        "note": "Tendance de forme du statut d'entraînement Garmin (évolution de la VO2 max).",
        "items": [
            {"id": "risk", "label": "En baisse (−1)", "min": None, "max": -0.5},
            {"id": "under", "label": "Stable (0)", "min": -0.5, "max": 0.5},
            {"id": "optimal", "label": "En hausse (+1)", "min": 0.5, "max": None},
        ],
    },
    "acwr": {
        "note": "Zones du ratio aiguë / chronique d'après Gabbett (2016).",
        "items": [{"id": z["id"], "label": z["label"], "min": z["min"], "max": z["max"]} for z in ACWR_ZONES],
    },
}

_BODY_BATTERY = {
    "note": "Plages Garmin de la Body Battery.",
    "items": [
        {"id": "risk", "label": "Très basse (0-25)", "min": None, "max": 26},
        {"id": "caution", "label": "Basse (26-50)", "min": 26, "max": 51},
        {"id": "optimal", "label": "Moyenne (51-75)", "min": 51, "max": 76},
        {"id": "good", "label": "Haute (76-100)", "min": 76, "max": None},
    ],
}
for _k in ("bb_at_wake", "bb_highest", "bb_lowest"):
    _FIXED[_k] = _BODY_BATTERY

# Jours de « report » d'une borne journalière sur les jours sans réponse Garmin.
_CARRY_DAYS = 3


def _daily_columns(conn: sqlite3.Connection, table: str, columns: tuple[str, ...],
                   dates: list[str]) -> list[tuple[float | None, ...]]:
    """Valeurs de ``columns`` pour chaque date, reportées au plus ``_CARRY_DAYS`` jours."""
    rows = conn.execute(
        f"SELECT date, {', '.join(columns)} FROM {table} "
        f"WHERE {' AND '.join(f'{c} IS NOT NULL' for c in columns)} AND date <= ? ORDER BY date",
        (dates[-1],),
    ).fetchall() if dates else []
    known = [r["date"] for r in rows]
    out: list[tuple[float | None, ...]] = []
    for d in dates:
        i = bisect_right(known, d) - 1
        if i >= 0 and (date.fromisoformat(d) - date.fromisoformat(known[i])).days <= _CARRY_DAYS:
            out.append(tuple(float(rows[i][c]) for c in columns))
        else:
            out.append((None,) * len(columns))
    return out


def _hrv(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any] | None:
    base = _daily_columns(conn, "daily_hrv",
                          ("baseline_low_upper", "baseline_balanced_low", "baseline_balanced_upper"), dates)
    if not any(b[0] is not None for b in base):
        return None
    low, bal_low, bal_up = ([b[i] for b in base] for i in range(3))
    edge = [None if v is None else 0 for v in low]   # bas / haut du graphique, seulement les jours connus
    return {
        "note": "Statut VFC Garmin : plages calculées chaque jour à partir de votre ligne de base personnelle.",
        "items": [
            {"id": "risk", "label": "Bas", "min": edge, "max": low},
            {"id": "caution", "label": "Déséquilibré", "min": low, "max": bal_low},
            {"id": "optimal", "label": "Équilibré", "min": bal_low, "max": bal_up},
            {"id": "caution", "label": "Déséquilibré", "min": bal_up, "max": [None if v is None else 1e9 for v in bal_up],
             "hideInLegend": True},
        ],
    }


def _vo2max(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any] | None:
    gender = repo.get_setting(conn, SETTING_GENDER)
    birth = repo.get_setting(conn, SETTING_BIRTH_DATE)
    if gender not in ("MALE", "FEMALE") or not birth:
        return {"note": "Catégories VO2 max indisponibles : le profil Garmin (âge, sexe) sera lu à la "
                        "prochaine synchronisation.", "items": []}
    table = _VO2_MALE if gender == "MALE" else _VO2_FEMALE
    thresholds = [table[bisect_right(_VO2_AGES, age)] for age in _ages(conn, dates) or []]
    bounds = [[None] * len(dates)] + [[t[i] for t in thresholds] for i in range(4)] + [[None] * len(dates)]
    return {
        "note": "Catégories VO2 max Garmin (Cooper Institute) selon votre âge à chaque date et votre sexe.",
        "items": [
            {"id": cid, "label": label,
             "min": bounds[i] if i else None, "max": bounds[i + 1] if i < 4 else None}
            for i, (cid, label) in enumerate(_VO2_LEVELS)
        ],
    }


def _ages(conn: sqlite3.Connection, dates: list[str]) -> list[int] | None:
    """Âge réel à chaque date, d'après la date de naissance du profil Garmin."""
    birth = repo.get_setting(conn, SETTING_BIRTH_DATE)
    if not birth:
        return None
    born = date.fromisoformat(birth[:10])
    return [day.year - born.year - ((day.month, day.day) < (born.month, born.day))
            for day in map(date.fromisoformat, dates)]


def _fitness_age(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any] | None:
    ages = _ages(conn, dates)
    if ages is None:
        return None
    return {
        "note": "Comparaison avec votre âge réel à chaque date (profil Garmin).",
        "items": [
            {"id": "optimal", "label": "Plus jeune que votre âge", "min": None, "max": ages},
            {"id": "caution", "label": "Plus âgé que votre âge", "min": ages, "max": None},
        ],
    }


def _acute_load(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any] | None:
    rng = _daily_columns(conn, "daily_training_load", ("chronic_min", "chronic_max"), dates)
    if not any(r[0] is not None for r in rng):
        return None
    lo, hi = [r[0] for r in rng], [r[1] for r in rng]
    return {
        "note": "Plage optimale de charge aiguë calculée chaque jour par Garmin.",
        "items": [
            {"id": "under", "label": "Sous la plage", "min": [None if v is None else 0 for v in lo], "max": lo},
            {"id": "optimal", "label": "Plage optimale", "min": lo, "max": hi},
            {"id": "caution", "label": "Au-dessus", "min": hi, "max": [None if v is None else 1e9 for v in hi]},
        ],
    }


_DYNAMIC = {"hrv": _hrv, "hrv_weekly": _hrv, "vo2max": _vo2max, "vo2max_cycling": _vo2max,
            "acute_load": _acute_load, "fitness_age": _fitness_age, "fitness_age_achievable": _fitness_age}


def zones_for(conn: sqlite3.Connection, key: str, dates: list[str]) -> dict[str, Any] | None:
    """Plages de fond de l'indicateur ``key`` pour les ``dates`` du graphique, ou None."""
    if key in _FIXED:
        return _FIXED[key]
    builder = _DYNAMIC.get(key)
    return builder(conn, dates) if builder and dates else None
