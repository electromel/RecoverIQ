"""Plages de couleur Garmin en fond des graphiques d'indicateurs."""

from recoveriq.analytics.zones import SETTING_BIRTH_DATE, SETTING_GENDER, zones_for
from recoveriq.db import repository as repo
from recoveriq.db.database import connect


def test_fixed_zones_cover_the_scale(db):
    with connect() as conn:
        z = zones_for(conn, "sleep_score", ["2026-11-01"])
        assert zones_for(conn, "rhr", ["2026-11-01"]) is None
    bounds = [(i["min"], i["max"]) for i in z["items"]]
    assert bounds[0][0] is None and bounds[-1][1] is None
    assert all(a[1] == b[0] for a, b in zip(bounds, bounds[1:]))     # plages jointives


def test_hrv_zones_follow_daily_baseline_with_short_carry(db):
    dates = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-08"]
    with connect() as conn:
        repo.upsert_rows(conn, "daily_hrv", [
            {"date": "2026-11-01", "baseline_low_upper": 40, "baseline_balanced_low": 45, "baseline_balanced_upper": 60},
            {"date": "2026-11-03", "baseline_low_upper": 42, "baseline_balanced_low": 47, "baseline_balanced_upper": 62},
        ])
        z = zones_for(conn, "hrv", dates)
    balanced = next(i for i in z["items"] if i["label"] == "Équilibré")
    assert balanced["min"] == [45, 45, 47, None]     # report sur le 02 ; trop loin pour le 08
    assert balanced["max"] == [60, 60, 62, None]
    low = next(i for i in z["items"] if i["label"] == "Bas")
    assert low["max"] == [40, 40, 42, None]


def test_vo2max_categories_depend_on_age_at_date(db):
    with connect() as conn:
        assert zones_for(conn, "vo2max", ["2026-11-01"])["items"] == []    # profil inconnu
        repo.set_setting(conn, SETTING_GENDER, "MALE")
        repo.set_setting(conn, SETTING_BIRTH_DATE, "1970-06-15")
        z = zones_for(conn, "vo2max", ["2020-06-14", "2020-06-15"])        # 49 ans puis 50 ans
    good = next(i for i in z["items"] if i["label"] == "Bon")
    assert good["min"] == [42.4, 39.2] and good["max"] == [46.4, 43.4]
    assert z["items"][0]["min"] is None and z["items"][-1]["max"] is None

