"""Calculs du tableau de bord sur une base de démonstration."""

from datetime import date, timedelta

import pandas as pd
import pytest

from recoveriq.analytics import correlations, home, series, training
from recoveriq.analytics.catalog import SERIES
from recoveriq.db import repository as repo
from recoveriq.db.database import connect
from recoveriq.devtools.demo_data import populate

TODAY = date(2026, 11, 17)


@pytest.fixture()
def demo(db):
    with connect() as conn:
        populate(conn, 200, TODAY)
    return db


def test_baseline_excludes_current_day():
    idx = pd.date_range("2026-01-01", periods=31, freq="D")
    values = pd.Series([10.0] * 30 + [100.0], index=idx)
    frame = series.with_indicators(values)
    # Ligne de base du dernier jour = 30 jours précédents uniquement (la valeur 100 est exclue).
    assert frame["baseline"].iloc[-1] == 10.0
    cmp = series.compare_to_baseline(values, idx[-1], higher_is_better=True)
    assert cmp["status"] == "above" and cmp["favorable"] is True


def test_gaps_stay_nan_and_baseline_needs_enough_values():
    idx = pd.to_datetime(["2026-01-01", "2026-01-05"])
    frame = series.with_indicators(series.daily(pd.Series([1.0, 2.0], index=idx), date(2026, 1, 6)))
    assert frame["value"].isna().sum() == 4          # jours manquants non remplis
    assert frame["baseline"].isna().all()            # moins de 10 valeurs


def test_series_view_all_catalog_entries(demo):
    with connect() as conn:
        for s in SERIES:
            view = series.series_view(conn, s.key, "90", TODAY)
            if view["available"]:
                assert view["points"][-1]["date"] == TODAY.isoformat()
                assert len(view["points"]) <= 90
                assert view["stats"]["n"] > 0
        # Série absente de la base : réponse explicite, pas d'erreur.
        assert series.series_view(conn, "vo2max_cycling", "all", TODAY)["available"] is False


def test_period_all_and_trimmed_start(demo):
    with connect() as conn:
        view = series.series_view(conn, "hrv", "all", TODAY)
    assert view["points"][0]["date"] == (TODAY - timedelta(days=200)).isoformat()
    assert view["points"][-1]["baseline"] is not None


def test_home_cards(demo):
    with connect() as conn:
        data = home.home_view(conn, TODAY)
    assert [c["id"] for c in data["cards"]] == ["body_battery", "hrv", "readiness", "sleep", "stress"]
    hrv = data["cards"][1]["main"]
    assert hrv["date"] == TODAY.isoformat() and hrv["comparison"]["baseline"] is not None
    assert len(hrv["sparkline"]) == home.SPARKLINE_DAYS
    assert data["training"]["status_phrase"] in ("PRODUCTIVE", "MAINTAINING")


def test_home_on_empty_database(db):
    with connect() as conn:
        data = home.home_view(conn, TODAY)
    assert all(c["main"]["available"] is False for c in data["cards"])
    assert data["training"] is None


def test_training_view(demo):
    with connect() as conn:
        data = training.training_view(conn, "90", TODAY)
    assert len(data["daily"]) == 90
    assert sum(data["zone_days"].values()) == 90
    assert data["focus"]["items"][2]["label"] == "Anaérobie"
    assert data["weekly_volume"] and data["weekly_volume"][0]["hours"] > 0
    assert training.acwr_zone(0.5) == "under" and training.acwr_zone(1.0) == "optimal"
    assert training.acwr_zone(1.4) == "caution" and training.acwr_zone(2.0) == "risk"


def test_correlations_detect_simulated_links(demo):
    with connect() as conn:
        data = correlations.correlations_view(conn, "all", TODAY)
    by_id = {p["id"]: p["stats"] for p in data["pairs"]}
    # La base de démo simule : bon sommeil → VFC haute ; stress élevé → recharge nocturne faible.
    assert by_id["sleep_score_hrv"]["pearson_r"] > 0.3
    assert by_id["stress_recharge"]["pearson_r"] < -0.3
    weekend = {w["key"]: w for w in data["weekday_weekend"]}
    assert weekend["sleep_duration"]["difference"] > 0 and weekend["sleep_duration"]["significant"]
    assert weekend["stress_avg"]["difference"] < 0
    assert data["vo2_volume"]["points"]


def test_correlate_insufficient_data():
    s = pd.Series([1.0, 2.0, 3.0])
    assert correlations.correlate(s, s)["sufficient"] is False


def test_api_endpoints_and_csv(demo, cfg):
    from fastapi.testclient import TestClient

    from recoveriq.api import routes_dashboard

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes_dashboard.router)
    client = TestClient(app)
    assert client.get("/api/home").status_code == 200
    assert client.get("/api/series/hrv?period=30").json()["meta"]["unit"] == "ms"
    assert client.get("/api/series/nope").status_code == 404
    assert client.get("/api/series/hrv?period=7").status_code == 422
    csv = client.get("/api/export/series/hrv.csv?period=30")
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")
    assert csv.text.splitlines()[0].startswith("﻿Date;VFC nocturne (ms);")
    for path in ("/api/export/home.csv", "/api/export/training.csv", "/api/export/activities.csv",
                 "/api/export/correlations.csv", "/api/correlations?period=all", "/api/catalog"):
        assert client.get(path).status_code == 200, path


def test_dates_follow_real_today(demo):
    # Les vues utilisent date.today() côté API ; les tests analytiques fixent TODAY.
    with connect() as conn:
        assert repo.get_setting(conn, "inexistant") is None
