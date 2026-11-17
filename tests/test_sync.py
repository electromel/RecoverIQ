"""Moteur de synchronisation, avec un faux client Garmin (aucun appel réseau)."""

from datetime import date, timedelta

from conftest import FakeAuth, FakeGarmin
from garminconnect import GarminConnectConnectionError

from recoveriq.db import repository as repo
from recoveriq.db.database import connect
from recoveriq.garmin.client import GarminClient, extract_status
from recoveriq.garmin.sync import (
    SETTING_BACKFILL_COMPLETE,
    SETTING_BACKFILL_FETCHERS,
    SETTING_BACKFILL_START,
    SETTING_LAST_SYNCED,
    SyncService,
    _aligned_blocks,
    _Job,
    backfill_needed,
)

TODAY = date(2026, 11, 17)


def make_service(cfg, garmin):
    auth = FakeAuth(garmin)
    client = GarminClient(auth, pause_s=0, jitter_s=0, sleep=lambda s: None)
    return SyncService(auth, cfg, today=lambda: TODAY, client=client)


def daily_dates(garmin, name):
    return sorted(args[0] for n, args in garmin.calls if n == name)


def test_incremental_resyncs_last_days(db, cfg):
    garmin = FakeGarmin()
    svc = make_service(cfg, garmin)
    svc._run(_Job("incremental", "test"))
    # Aujourd'hui + 3 jours précédents
    assert daily_dates(garmin, "user_summary") == [(TODAY - timedelta(days=i)).isoformat() for i in (3, 2, 1, 0)]
    assert len(daily_dates(garmin, "endurance_day")) == 4      # variante journalière
    assert not [c for c in garmin.calls if c[0] == "endurance_score"]
    with connect() as conn:
        assert repo.get_setting(conn, SETTING_LAST_SYNCED) == TODAY.isoformat()
        run = repo.list_runs(conn)[0]
        assert conn.execute("SELECT COUNT(*) FROM daily_rhr").fetchone()[0] == 4
    assert run["status"] == "success" and run["days_processed"] == 4


def test_incremental_catches_up_missed_days(db, cfg):
    with connect() as conn:
        repo.set_setting(conn, SETTING_LAST_SYNCED, (TODAY - timedelta(days=10)).isoformat())
    garmin = FakeGarmin()
    make_service(cfg, garmin)._run(_Job("incremental", "test"))
    assert len(daily_dates(garmin, "user_summary")) == 11


def test_backfill_resumes_and_stops_on_empty_streak(db, cfg):
    start = TODAY - timedelta(days=40)
    with connect() as conn:
        repo.set_setting(conn, SETTING_BACKFILL_START, start.isoformat())

    # Données seulement sur les 20 derniers jours : arrêt après 5 jours vides (cfg).
    garmin = FakeGarmin(data_until=TODAY - timedelta(days=19))
    make_service(cfg, garmin)._run(_Job("backfill", "test"))

    hrv_days = daily_dates(garmin, "hrv")
    assert len(hrv_days) == 20 + 5          # 20 jours avec données + 5 jours vides avant arrêt
    # training_status est toujours vide dans le faux client : arrêt rapide aussi.
    assert len(daily_dates(garmin, "training_status")) == 5

    with connect() as conn:
        assert repo.get_setting(conn, SETTING_BACKFILL_COMPLETE) is True
        run = repo.list_runs(conn)[0]
    assert run["status"] == "success" and "Arrêt anticipé" in run["message"]

    # Relance : tout est déjà fait, aucun nouvel appel journalier.
    garmin2 = FakeGarmin()
    make_service(cfg, garmin2)._run(_Job("backfill", "test"))
    assert daily_dates(garmin2, "user_summary") == []


def test_raw_only_fetchers_count_detail_for_empty_streak(db, cfg):
    """FC et stress de la journée : sans table normalisée, l'arrêt dépend des mesures présentes."""
    start = TODAY - timedelta(days=40)
    with connect() as conn:
        repo.set_setting(conn, SETTING_BACKFILL_START, start.isoformat())
    garmin = FakeGarmin(data_until=TODAY - timedelta(days=19))
    make_service(cfg, garmin)._run(_Job("backfill", "test"))
    assert len(daily_dates(garmin, "heart_rates")) == 20 + 5
    assert len(daily_dates(garmin, "stress")) == 20 + 5
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM raw_response WHERE fetcher = 'heart_rates'").fetchone()[0]
    assert n == 25


def test_backfill_rerun_when_a_fetcher_is_added(db, cfg):
    with connect() as conn:
        repo.set_setting(conn, SETTING_BACKFILL_START, (TODAY - timedelta(days=5)).isoformat())
    assert backfill_needed()                                   # jamais terminé
    make_service(cfg, FakeGarmin())._run(_Job("backfill", "test"))
    assert not backfill_needed()

    # Ancienne installation : import terminé avant l'ajout de « heart_rates ».
    with connect() as conn:
        covered = repo.get_setting(conn, SETTING_BACKFILL_FETCHERS)
        repo.set_setting(conn, SETTING_BACKFILL_FETCHERS, [n for n in covered if n != "heart_rates"])
        conn.execute("DELETE FROM import_progress WHERE fetcher = 'heart_rates'")
    assert backfill_needed()
    garmin = FakeGarmin()
    make_service(cfg, garmin)._run(_Job("backfill", "test"))
    assert len(daily_dates(garmin, "heart_rates")) == 6        # seule la nouvelle série est remontée
    assert daily_dates(garmin, "user_summary") == []
    assert not backfill_needed()


def test_backfill_records_errors_and_retries_them(db, cfg):
    start = TODAY - timedelta(days=2)
    failing = (TODAY - timedelta(days=1)).isoformat()
    with connect() as conn:
        repo.set_setting(conn, SETTING_BACKFILL_START, start.isoformat())
    garmin = FakeGarmin(fail_dates={failing})
    make_service(cfg, garmin)._run(_Job("backfill", "test"))
    with connect() as conn:
        run = repo.list_runs(conn)[0]
        assert run["status"] == "partial" and run["errors_count"] == 7   # 7 fetchers journaliers
        assert repo.progress_summary(conn)["error"] == 7

    # Seconde passe : seuls les appels en erreur sont rejoués.
    garmin2 = FakeGarmin()
    make_service(cfg, garmin2)._run(_Job("backfill", "test"))
    assert daily_dates(garmin2, "user_summary") == [failing]
    with connect() as conn:
        assert repo.progress_summary(conn).get("error", 0) == 0


def test_aligned_blocks_are_stable_and_cover_range():
    start, end = date(2026, 1, 15), date(2026, 11, 17)
    blocks = _aligned_blocks(start, end, 30)
    assert blocks[0][1] == end and blocks[-1][0] == start
    covered = sum((b - a).days + 1 for a, b in blocks)
    assert covered == (end - start).days + 1
    # Le lendemain, les débuts de blocs (clés de reprise) restent identiques.
    next_day = _aligned_blocks(start, end + timedelta(days=1), 30)
    assert {a for a, _ in blocks} <= {a for a, _ in next_day}


def test_extract_status_from_library_messages():
    assert extract_status(GarminConnectConnectionError("API Error 404 - Not Found")) == 404
    assert extract_status(GarminConnectConnectionError("HTTP error: API Error 429")) == 429
    assert extract_status(GarminConnectConnectionError("API client error (403): x")) == 403
    assert extract_status(GarminConnectConnectionError("Connection error: timeout")) is None


def test_client_classifies_outcomes(db):
    garmin = FakeGarmin()
    client = GarminClient(FakeAuth(garmin), pause_s=0, jitter_s=0, sleep=lambda s: None)

    def not_found(_):
        raise GarminConnectConnectionError("API Error 404 - Not Found")

    def server_error(_):
        raise GarminConnectConnectionError("API Error 500")

    assert client.call("x", not_found).outcome == "unsupported"
    assert client.call("x", server_error).outcome == "error"
    assert client.call("x", lambda g: {}).outcome == "empty"
    assert client.call("x", lambda g: {"a": 1}).outcome == "ok"
