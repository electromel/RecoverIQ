"""Catalogue des indicateurs normalisés (table SQLite → libellé affiché)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    table: str
    label: str
    key: str = "date"  # colonne clé primaire
    listed: bool = True  # affiché dans l'état des données (page Synchronisation)
    newer_by: str | None = None  # si renseignée : une ligne existante n'est remplacée que par une plus récente


METRICS: tuple[Metric, ...] = (
    Metric("daily_body_battery", "Body Battery"),
    Metric("daily_hrv", "VFC (HRV)"),
    Metric("daily_training_load", "Charge d'entraînement"),
    Metric("daily_training_status", "Statut d'entraînement"),
    Metric("daily_intensity", "Minutes d'intensité"),
    Metric("daily_vo2max", "VO2 max"),
    Metric("daily_stress", "Stress"),
    Metric("daily_sleep", "Sommeil"),
    Metric("daily_rhr", "FC au repos"),
    Metric("daily_readiness", "Training Readiness"),
    Metric("daily_endurance", "Endurance Score"),
    Metric("daily_hill", "Hill Score"),
    Metric("daily_respiration", "Fréquence respiratoire"),
    Metric("daily_spo2", "SpO2"),
    Metric("daily_lactate_threshold", "Seuil lactique"),
    Metric("daily_fitness_age", "Âge de forme physique"),
    Metric("activity", "Activités", key="activity_id"),
    Metric("readiness_event", "Relevés Training Readiness", key="timestamp_local", listed=False),
    Metric("device", "Montres", key="device_id", listed=False, newer_by="date"),
)

METRICS_BY_TABLE = {m.table: m for m in METRICS}
