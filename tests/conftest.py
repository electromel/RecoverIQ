"""Fixtures partagées : base temporaire et faux client Garmin."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from recoveriq.config import Settings
from recoveriq.db.database import init_db


@pytest.fixture()
def db(tmp_path):
    init_db(tmp_path / "test.db")
    return tmp_path / "test.db"


@pytest.fixture()
def cfg(tmp_path) -> Settings:
    return Settings(home=tmp_path, request_pause_s=0, empty_streak_stop_days=5, resync_days=3)


class FakeGarmin:
    """Imite les méthodes de garminconnect.Garmin utilisées par le registre."""

    def __init__(self, data_until: date | None = None, fail_dates: set[str] | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.data_until = data_until          # aucune donnée avant cette date
        self.fail_dates = fail_dates or set()

    def _has(self, d: str) -> bool:
        return self.data_until is None or d >= self.data_until.isoformat()

    def _log(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if args and args[0] in self.fail_dates:
            raise RuntimeError("panne simulée")

    def get_user_summary(self, d):
        self._log("user_summary", d)
        return {"restingHeartRate": 50, "averageStressLevel": 30} if self._has(d) else {}

    def get_hrv_data(self, d):
        self._log("hrv", d)
        return {"hrvSummary": {"lastNightAvg": 60}} if self._has(d) else {}

    def get_training_status(self, d):
        self._log("training_status", d)
        return {}

    def get_sleep_data(self, d):
        self._log("sleep", d)
        return {"dailySleepDTO": {"calendarDate": d, "sleepTimeSeconds": 28000}} if self._has(d) else {}

    def get_training_readiness(self, d):
        self._log("training_readiness", d)
        return []

    def get_heart_rates(self, d):
        self._log("heart_rates", d)
        return {"calendarDate": d, "heartRateValues": [[1_000_000, 60]] if self._has(d) else None}

    def get_stress_data(self, d):
        self._log("stress", d)
        return {"calendarDate": d, "stressValuesArray": [[1_000_000, 25]] if self._has(d) else []}

    def get_body_battery(self, s, e):
        self._log("body_battery", s, e)
        return []

    def get_hill_score(self, s, e):
        self._log("hill_score", s, e)
        return {}

    def get_endurance_score(self, s, e=None):
        self._log("endurance_score" if e else "endurance_day", s, e)
        return {}

    def get_activities_by_date(self, s, e):
        self._log("activities", s, e)
        return []

    def get_user_profile(self):
        self._log("profile")
        return {"userData": {"gender": "MALE", "birthDate": "1970-06-15"}}

    def count_activities(self):
        return 0


class FakeAuth:
    def __init__(self, garmin: FakeGarmin) -> None:
        self.garmin = garmin

    def client(self):
        return self.garmin

    def restore(self):
        pass

    def persist_tokens(self):
        pass

    def invalidate(self, reason):
        pass


@pytest.fixture()
def fake_garmin() -> FakeGarmin:
    return FakeGarmin()
