"""Calculs du tableau de bord sur une base de démonstration."""

from datetime import date, timedelta
from pathlib import Path

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
    assert len(client.get("/api/day/2026-11-10").json()["dates"]) == 3
    assert client.get("/api/day/pas-une-date").status_code == 422
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


def test_day_view_three_days_with_intraday_from_raw(demo):
    from recoveriq.analytics.day import day_view

    d = TODAY - timedelta(days=10)
    sleep = {
        "dailySleepDTO": {"calendarDate": d.isoformat(), "sleepStartTimestampGMT": 1_000_000,
                          "sleepEndTimestampGMT": 2_000_000},
        "sleepHeartRate": [{"startGMT": 1_000_000, "value": 55}, {"startGMT": 1_060_000, "value": -1}],
        "sleepLevels": [{"startGMT": "2026-11-06T22:00:00.0", "endGMT": "2026-11-06T22:30:00.0", "activityLevel": 0.0}],
        "wellnessEpochSPO2DataDTOList": [{"epochTimestamp": "2026-11-06T22:01:00.0", "spo2Reading": 95}],
    }
    with connect() as conn:
        repo.save_raw(conn, "sleep", d.isoformat(), d.isoformat(), "ok", sleep)
        repo.save_raw(conn, "sleep", "2020-01-01", "2020-01-01", "ok", {"sleepHeartRate": [{"startGMT": 5, "value": 99}]})
        view = day_view(conn, d)

    assert view["dates"] == [(d + timedelta(days=i - 1)).isoformat() for i in range(3)]
    assert len(view["daily"]) == len(SERIES)
    assert all(len(r["values"]) == 3 for r in view["daily"])
    hrv = next(r for r in view["daily"] if r["key"] == "hrv")
    assert hrv["values"][1] is not None
    intr = view["intraday"]
    assert intr["heart_rate"] == [[1_000_000, 55.0]]          # -1 écarté, autre date ignorée
    assert intr["sleep_stages"][0]["level"] == 0
    assert intr["spo2"][0][1] == 95.0
    assert intr["nights"] == [{"start": 1_000_000, "end": 2_000_000, "date": d.isoformat()}]
    assert all(a["date"] in view["dates"] for a in view["activities"])
    assert intr["day_series"] == []


def test_day_view_full_day_series_take_precedence(demo):
    from recoveriq.analytics.day import intraday

    d = TODAY - timedelta(days=10)
    sleep = {"sleepHeartRate": [{"startGMT": 1_000_030, "value": 70}, {"startGMT": 9_000_000, "value": 48}]}
    hr = {"heartRateValues": [[1_000_000, 55], [1_120_000, None], [1_240_000, 57]]}
    stress = {"stressValuesArray": [[1_000_000, 20], [1_180_000, -1]],
              "bodyBatteryValuesArray": [[1_000_000, "MEASURED", 80, 3.0]]}
    with connect() as conn:
        repo.save_raw(conn, "sleep", d.isoformat(), d.isoformat(), "ok", sleep)
        repo.save_raw(conn, "heart_rates", d.isoformat(), d.isoformat(), "ok", hr)
        repo.save_raw(conn, "stress", d.isoformat(), d.isoformat(), "ok", stress)
        intr = intraday(conn, d - timedelta(days=1), d + timedelta(days=1))

    # Le point de sommeil couvert par la journée est écarté ; celui hors plage est gardé.
    assert intr["heart_rate"] == [[1_000_000, 55.0], [1_240_000, 57.0], [9_000_000, 48.0]]
    assert intr["stress"] == [[1_000_000, 20.0]]
    assert intr["body_battery"][0] == [1_000_000, 80.0]
    assert intr["day_series"] == ["body_battery", "heart_rate", "stress"]


def test_series_view_includes_garmin_zones(demo):
    with connect() as conn:
        readiness = series.series_view(conn, "readiness", "90", TODAY)
        rhr = series.series_view(conn, "rhr", "90", TODAY)
    assert readiness["zones"]["items"][0]["id"] == "risk"
    assert rhr["zones"] is None


def test_activity_recovery_time_after_effort(db):
    def act(i, start, duration_s):
        return {"activity_id": i, "date": start[:10], "start_local": start, "type": "running", "duration_s": duration_s}

    def event(ts, minutes, context="AFTER_POST_EXERCISE_RESET"):
        return {"timestamp_local": ts, "date": ts[:10], "context": context, "score": 60, "recovery_time_min": minutes}

    with connect() as conn:
        repo.upsert_rows(conn, "activity", [
            act(1, "2026-03-01 10:00:00", 3600),   # relevé 1 min après la fin
            act(2, "2026-03-02 09:00:00", 1800),   # échauffement : son relevé précède la séance suivante
            act(3, "2026-03-02 09:40:00", 3600),
            act(4, "2026-03-03 10:00:00", 3600),   # relevé trop tardif (> 3 h après la fin)
            act(5, "2026-03-04 10:00:00", 3600),   # aucun relevé
        ])
        repo.upsert_rows(conn, "readiness_event", [
            event("2026-03-01 07:00:00", 5, "AFTER_WAKEUP_RESET"),
            event("2026-03-01 11:01:00", 900),
            event("2026-03-02 09:30:10", 300),
            event("2026-03-02 10:40:20", 1500),
            event("2026-03-03 15:00:00", 700),
        ])
        rows = {r["activity_id"]: r["recovery_time_min"]
                for r in training.activities_list(conn, "all", date(2026, 3, 10))}
    assert rows == {1: 900, 2: 300, 3: 1500, 4: None, 5: None}


def test_migration_fills_events_from_raw_responses(tmp_path):
    import json
    import sqlite3

    from recoveriq.db import database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript((Path(database.__file__).parent / "schema.sql").read_text("utf-8"))
    conn.executescript((Path(database.__file__).parent / "migration_002_ai.sql").read_text("utf-8"))
    conn.execute("PRAGMA user_version=2")
    conn.execute(
        "INSERT INTO raw_response (fetcher, start_date, end_date, fetched_at, outcome, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("training_readiness", "2026-11-17", "2026-11-17", "x", "ok", json.dumps([
            {"timestampLocal": "2026-11-17T17:34:30.0", "inputContext": "AFTER_POST_EXERCISE_RESET",
             "score": 77, "recoveryTime": 1457},
            {"timestampLocal": "2026-11-17T07:37:25.0", "inputContext": "AFTER_WAKEUP_RESET",
             "score": 97, "recoveryTime": -1},
        ])))
    conn.execute(
        "INSERT INTO raw_response (fetcher, start_date, end_date, fetched_at, outcome, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("training_readiness", "2026-11-16", "2026-11-16", "x", "ok", "pas du json"))
    conn.commit()
    conn.close()

    database.init_db(path)
    with connect() as c:
        events = [tuple(r) for r in c.execute(
            "SELECT timestamp_local, date, context, score, recovery_time_min FROM readiness_event ORDER BY 1")]
    assert events == [
        ("2026-11-17 07:37:25", "2026-11-17", "AFTER_WAKEUP_RESET", 97, None),
        ("2026-11-17 17:34:30", "2026-11-17", "AFTER_POST_EXERCISE_RESET", 77, 1457),
    ]


def test_migration_fills_devices_from_raw_responses(tmp_path):
    import json
    import sqlite3

    from recoveriq.db import database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript((Path(database.__file__).parent / "schema.sql").read_text("utf-8"))
    conn.executescript((Path(database.__file__).parent / "migration_002_ai.sql").read_text("utf-8"))
    conn.execute("PRAGMA user_version=2")
    conn.execute("INSERT INTO activity (activity_id, date, start_local) VALUES (1, '2024-01-01', '2024-01-01 10:00:00')")
    conn.execute("INSERT INTO activity (activity_id, date, start_local) VALUES (2, '2015-01-01', '2015-01-01 10:00:00')")
    raw = "INSERT INTO raw_response (fetcher, start_date, end_date, fetched_at, outcome, payload) VALUES (?, ?, ?, 'x', 'ok', ?)"
    conn.execute(raw, ("activities", "2024-01-01", "2024-01-31", json.dumps([
        {"activityId": 1, "deviceId": 398}, {"activityId": 2}])))
    status = lambda name: json.dumps({"mostRecentTrainingStatus": {"recordedDevices": [{"deviceId": 398, "deviceName": name}]}})
    conn.execute(raw, ("training_status", "2023-12-07", "2023-12-07", status("other.device")))
    conn.execute(raw, ("training_status", "2023-12-08", "2023-12-08", status("fenix 5S Plus")))
    conn.execute(raw, ("training_status", "2023-01-01", "2023-01-01", status("ancien nom")))
    conn.commit()
    conn.close()

    database.init_db(path)
    with connect() as c:
        assert [tuple(r) for r in c.execute("SELECT activity_id, device_id FROM activity ORDER BY 1")] == [(1, 398), (2, None)]
        assert [tuple(r) for r in c.execute("SELECT * FROM device")] == [(398, "fenix 5S Plus", "2023-12-08")]
        # l'import historique remonte le temps : un nom plus ancien ne remplace pas le récent
        repo.upsert_rows(c, "device", [{"device_id": 398, "name": "ancien nom", "date": "2023-01-01"}])
        repo.upsert_rows(c, "device", [{"device_id": 398, "name": "fenix 5S Plus", "date": "2024-08-15"}])
        assert tuple(c.execute("SELECT * FROM device").fetchone()) == (398, "fenix 5S Plus", "2024-08-15")


def test_devices_view_and_day_devices(db):
    from recoveriq.analytics import day as day_mod
    from recoveriq.analytics.devices import devices_view

    def act(i, d, device_id, kind="running"):
        return {"activity_id": i, "date": d, "start_local": f"{d} 10:00:00", "type": kind,
                "duration_s": 3600, "distance_m": 10000, "device_id": device_id}

    with connect() as conn:
        repo.upsert_rows(conn, "activity", [
            act(1, "2015-05-01", None), act(2, "2019-01-14", 0, "rock_climbing"),
            act(3, "2020-03-01", 398), act(4, "2021-03-01", 398, "hiking"), act(5, "2016-01-01", 344),
        ])
        repo.upsert_rows(conn, "device", [{"device_id": 398, "name": "fenix 5S Plus", "date": "2021-03-01"}])
        view = devices_view(conn)
        days = day_mod.day_view(conn, date(2020, 3, 1))
    by_id = {r["device_id"]: r for r in view}
    assert [r["device_id"] for r in view] == [None, 344, 0, 398]
    assert by_id[398]["label"] == "fenix 5S Plus" and by_id[398]["activities"] == 2
    assert by_id[398]["first_date"] == "2020-03-01" and by_id[398]["last_date"] == "2021-03-01"
    assert by_id[398]["distance_m"] == 20000
    assert by_id[344]["label"] == "Modèle inconnu"
    assert by_id[0]["label"].startswith("Aucune montre") and by_id[None]["label"] == "Non indiquée par Garmin"
    assert days["activities"][0]["device"] == "fenix 5S Plus"
    assert days["devices"]["2020-03-01"] == {"activities": ["fenix 5S Plus"], "primary": []}
    assert days["devices"]["2020-03-02"] == {"activities": [], "primary": []}
