"""Couche d'accès : fusion non destructive, disponibilité, paramètres."""

import pytest

from recoveriq.db import repository as repo
from recoveriq.db.database import connect


def test_upsert_merges_without_erasing(db):
    with connect() as conn:
        repo.upsert_rows(conn, "daily_body_battery", [{"date": "2026-11-10", "highest": 80, "charged": 50}])
        repo.upsert_rows(conn, "daily_body_battery", [{"date": "2026-11-10", "highest": None, "sleep_charge": 30}])
        row = dict(conn.execute("SELECT * FROM daily_body_battery").fetchone())
    assert row["highest"] == 80 and row["charged"] == 50 and row["sleep_charge"] == 30


def test_upsert_rejects_unknown_table_or_column(db):
    with connect() as conn:
        with pytest.raises(ValueError):
            repo.upsert_rows(conn, "sqlite_master", [{"date": "x"}])
        with pytest.raises(ValueError):
            repo.upsert_rows(conn, "daily_hrv", [{"date": "x", "nope": 1}])


def test_availability_states(db):
    with connect() as conn:
        repo.touch_availability(conn, "daily_hill", [])
        repo.touch_availability(conn, "daily_hrv", ["2026-11-01"])
        repo.touch_availability(conn, "daily_hrv", ["2026-10-01", "2026-11-05"])
        repo.touch_availability(conn, "daily_hrv", [])
        overview = {r["metric"]: r for r in repo.data_overview(conn)}
        avail = dict(conn.execute("SELECT * FROM metric_availability WHERE metric='daily_hrv'").fetchone())
    assert overview["daily_hill"]["state"] == "not_provided"
    assert overview["daily_hrv"]["state"] == "available"
    assert overview["daily_sleep"]["state"] == "unknown"
    assert (avail["first_seen"], avail["last_seen"]) == ("2026-10-01", "2026-11-05")


def test_settings_roundtrip(db):
    with connect() as conn:
        repo.set_setting(conn, "a", {"x": [1, 2]})
        assert repo.get_setting(conn, "a") == {"x": [1, 2]}
        repo.delete_setting(conn, "a")
        assert repo.get_setting(conn, "a", "def") == "def"
