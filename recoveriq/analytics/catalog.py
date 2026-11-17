"""Catalogue des séries affichables : une série = une colonne d'une table journalière.

Ajouter une courbe au tableau de bord = ajouter une entrée ici. ``scale`` convertit
l'unité de stockage vers l'unité d'affichage (ex. secondes → heures).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    key: str
    table: str
    column: str
    label: str
    unit: str
    group: str
    higher_is_better: bool | None = True   # None = ni bon ni mauvais (ex. charge)
    scale: float = 1.0
    decimals: int = 0


SERIES: tuple[Series, ...] = (
    # Body Battery
    Series("bb_at_wake", "daily_body_battery", "at_wake", "Body Battery au réveil", "", "Body Battery"),
    Series("bb_highest", "daily_body_battery", "highest", "Body Battery max", "", "Body Battery"),
    Series("bb_lowest", "daily_body_battery", "lowest", "Body Battery min", "", "Body Battery"),
    Series("bb_charged", "daily_body_battery", "charged", "Body Battery : recharge", "", "Body Battery"),
    Series("bb_drained", "daily_body_battery", "drained", "Body Battery : décharge", "", "Body Battery", higher_is_better=False),
    Series("bb_sleep_charge", "daily_body_battery", "sleep_charge", "Body Battery : recharge nocturne", "", "Body Battery"),
    # VFC / FC
    Series("hrv", "daily_hrv", "last_night_avg", "VFC nocturne", "ms", "Cœur"),
    Series("hrv_weekly", "daily_hrv", "weekly_avg", "VFC moyenne 7 j (Garmin)", "ms", "Cœur"),
    Series("rhr", "daily_rhr", "resting_hr", "FC au repos", "bpm", "Cœur", higher_is_better=False),
    # Sommeil
    Series("sleep_score", "daily_sleep", "score", "Score de sommeil", "", "Sommeil"),
    Series("sleep_duration", "daily_sleep", "duration_s", "Durée de sommeil", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_deep", "daily_sleep", "deep_s", "Sommeil profond", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_light", "daily_sleep", "light_s", "Sommeil léger", "h", "Sommeil", higher_is_better=None, scale=1 / 3600, decimals=2),
    Series("sleep_rem", "daily_sleep", "rem_s", "Sommeil paradoxal", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_awake", "daily_sleep", "awake_s", "Éveil nocturne", "min", "Sommeil", higher_is_better=False, scale=1 / 60),
    Series("resp_sleep", "daily_respiration", "sleep_avg", "Respiration nocturne", "rpm", "Sommeil", higher_is_better=None, decimals=1),
    Series("spo2_sleep", "daily_spo2", "sleep_avg", "SpO2 nocturne", "%", "Sommeil", decimals=1),
    # Stress
    Series("stress_avg", "daily_stress", "avg", "Stress moyen", "", "Stress", higher_is_better=False),
    Series("stress_high", "daily_stress", "high_s", "Stress élevé", "min", "Stress", higher_is_better=False, scale=1 / 60),
    Series("stress_rest", "daily_stress", "rest_s", "Repos (stress)", "h", "Stress", scale=1 / 3600, decimals=1),
    # Récupération
    Series("readiness", "daily_readiness", "score", "Training Readiness", "", "Récupération"),
    Series("recovery_time", "daily_readiness", "recovery_time_min", "Temps de récupération", "h", "Récupération",
           higher_is_better=False, scale=1 / 60, decimals=1),
    # Entraînement
    Series("intensity", "daily_intensity", "total_min", "Minutes d'intensité", "min", "Entraînement"),
    Series("acute_load", "daily_training_load", "acute_load", "Charge aiguë", "", "Entraînement", higher_is_better=None),
    Series("chronic_load", "daily_training_load", "chronic_load", "Charge chronique", "", "Entraînement", higher_is_better=None),
    Series("acwr", "daily_training_load", "acwr", "Ratio aiguë / chronique", "", "Entraînement", higher_is_better=None, decimals=2),
    Series("vo2max", "daily_vo2max", "running", "VO2 max (course)", "ml/kg/min", "Forme", decimals=1),
    Series("vo2max_cycling", "daily_vo2max", "cycling", "VO2 max (vélo)", "ml/kg/min", "Forme", decimals=1),
    Series("endurance", "daily_endurance", "score", "Endurance Score", "", "Forme"),
    Series("hill", "daily_hill", "overall", "Hill Score", "", "Forme"),
)

SERIES_BY_KEY = {s.key: s for s in SERIES}

# Périodes du sélecteur (jours ; None = tout l'historique).
PERIODS: dict[str, int | None] = {"30": 30, "90": 90, "365": 365, "all": None}
