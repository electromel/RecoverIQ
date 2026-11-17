"""Données du tableau de bord (JSON) et exports CSV de chaque vue."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from recoveriq.analytics.catalog import PERIODS, SERIES, SERIES_BY_KEY
from recoveriq.analytics.correlations import correlations_view
from recoveriq.analytics.day import day_view
from recoveriq.analytics.home import home_view
from recoveriq.analytics.series import series_view
from recoveriq.analytics.training import activities_list, training_view
from recoveriq.api.csv_export import csv_response
from recoveriq.db.database import connect

router = APIRouter(prefix="/api", tags=["dashboard"])

PeriodQuery = Query("90", pattern="^(" + "|".join(PERIODS) + ")$")


def _today() -> date:
    return date.today()


def _check_series(key: str) -> None:
    if key not in SERIES_BY_KEY:
        raise HTTPException(404, f"Série inconnue : {key}")


# --- JSON ----------------------------------------------------------------------

@router.get("/catalog")
def catalog() -> dict[str, Any]:
    with connect() as conn:
        available = {
            s.key: conn.execute(
                f"SELECT 1 FROM {s.table} WHERE {s.column} IS NOT NULL LIMIT 1").fetchone() is not None
            for s in SERIES
        }
    return {
        "periods": list(PERIODS),
        "series": [{"key": s.key, "label": s.label, "unit": s.unit, "group": s.group,
                    "available": available[s.key]} for s in SERIES],
    }


@router.get("/home")
def home() -> dict[str, Any]:
    with connect() as conn:
        return home_view(conn, _today())


@router.get("/series/{key}")
def series(key: str, period: str = PeriodQuery) -> dict[str, Any]:
    _check_series(key)
    with connect() as conn:
        return series_view(conn, key, period, _today())


@router.get("/day/{day}")
def day_detail(day: date) -> dict[str, Any]:
    with connect() as conn:
        return day_view(conn, day)


@router.get("/training")
def training(period: str = PeriodQuery) -> dict[str, Any]:
    with connect() as conn:
        return training_view(conn, period, _today())


@router.get("/activities")
def activities(period: str = PeriodQuery) -> list[dict[str, Any]]:
    with connect() as conn:
        return activities_list(conn, period, _today())


@router.get("/correlations")
def correlations(period: str = PeriodQuery) -> dict[str, Any]:
    with connect() as conn:
        return correlations_view(conn, period, _today())


# --- CSV -----------------------------------------------------------------------

@router.get("/export/home.csv")
def export_home() -> Response:
    data = home()
    rows = []
    for card in data["cards"]:
        for m in [card["main"], *card["secondary"]]:
            cmp = m.get("comparison") or {}
            rows.append({"card": card["title"], "metric": m["label"], "unit": m["unit"], "date": m["date"],
                         "value": m["value"], "baseline": cmp.get("baseline"), "std": cmp.get("std"),
                         "delta": cmp.get("delta"), "delta_pct": cmp.get("delta_pct"), "z": cmp.get("z"),
                         "status": cmp.get("status")})
    return csv_response("accueil", [
        ("card", "Carte"), ("metric", "Indicateur"), ("unit", "Unité"), ("date", "Date"), ("value", "Valeur"),
        ("baseline", "Ligne de base 30 j"), ("std", "Écart type"), ("delta", "Écart"),
        ("delta_pct", "Écart %"), ("z", "Score z"), ("status", "Statut"),
    ], rows)


@router.get("/export/series/{key}.csv")
def export_series(key: str, period: str = PeriodQuery) -> Response:
    data = series(key, period)
    unit = f" ({data['meta']['unit']})" if data["meta"]["unit"] else ""
    return csv_response(f"{key}_{period}", [
        ("date", "Date"), ("value", f"{data['meta']['label']}{unit}"), ("ma7", "Moyenne mobile 7 j"),
        ("ma28", "Moyenne mobile 28 j"), ("baseline", "Ligne de base 30 j"),
        ("band_low", "Bande basse"), ("band_high", "Bande haute"),
    ], data["points"])


@router.get("/export/training.csv")
def export_training(period: str = PeriodQuery) -> Response:
    data = training(period)
    return csv_response(f"charge_{period}", [
        ("date", "Date"), ("acute_load", "Charge aiguë"), ("chronic_load", "Charge chronique"),
        ("acwr", "Ratio A/C"), ("zone", "Zone"), ("acwr_status", "Statut Garmin"),
        ("focus_low_aerobic", "Focus aérobie basse"), ("focus_high_aerobic", "Focus aérobie haute"),
        ("focus_anaerobic", "Focus anaérobie"),
    ], data["daily"])


@router.get("/export/activities.csv")
def export_activities(period: str = PeriodQuery) -> Response:
    return csv_response(f"activites_{period}", [
        ("start_local", "Début"), ("type", "Type"), ("name", "Nom"), ("duration_s", "Durée (s)"),
        ("distance_m", "Distance (m)"), ("elev_gain_m", "D+ (m)"), ("avg_hr", "FC moy"),
        ("max_hr", "FC max"), ("training_load", "Charge"), ("aerobic_te", "Effet aérobie"),
        ("anaerobic_te", "Effet anaérobie"),
    ], activities(period))


@router.get("/export/correlations.csv")
def export_correlations(period: str = PeriodQuery) -> Response:
    data = correlations(period)
    rows = []
    for p in data["pairs"]:
        rows.append({"analysis": f"{p['x']['label']} → {p['y']['label']}", "note": p["note"], **p["stats"]})
    vo2 = data["vo2_volume"]
    for kind, label in (("level", "Volume 4 sem. → VO2 max"), ("change", "Volume 4 sem. → variation VO2 max")):
        rows.append({"analysis": label, "note": "Hebdomadaire", **vo2[kind]})
    for w in data["weekday_weekend"]:
        rows.append({"analysis": f"{w['label']} : week-end vs semaine", "note":
                     f"semaine {w['weekday_mean']} / week-end {w['weekend_mean']}",
                     "n": w["weekday_n"] + w["weekend_n"], "pearson_p": w["p_value"],
                     "strength": f"d = {w['cohen_d']}" if w["cohen_d"] is not None else "—"})
    return csv_response(f"correlations_{period}", [
        ("analysis", "Analyse"), ("note", "Détail"), ("n", "n"), ("pearson_r", "r (Pearson)"),
        ("pearson_p", "p"), ("spearman_rho", "rho (Spearman)"), ("spearman_p", "p Spearman"),
        ("slope", "Pente"), ("strength", "Intensité"),
    ], rows)
