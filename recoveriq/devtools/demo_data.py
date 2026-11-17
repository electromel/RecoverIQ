"""Génère une base de démonstration réaliste (aucun appel Garmin).

Usage : ``python -m recoveriq.devtools.demo_data <dossier> [jours]``, puis lancer
l'application avec ``RECOVERIQ_HOME=<dossier>``. Sert aussi de jeu de données aux tests.

Les données simulent des liens plausibles (bonne nuit → VFC et Body Battery plus hautes,
journée stressée → recharge nocturne plus faible, sommeil plus long le week-end), pour
que la vue corrélations ait quelque chose à montrer.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from recoveriq.db import repository as repo
from recoveriq.db.database import connect, init_db


def populate(conn: sqlite3.Connection, days: int, today: date, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    acute = chronic = 300.0
    vo2 = 48.0
    prev_stress = 30.0
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        weekend = d.weekday() >= 5
        sleep_h = rng.normal(7.9 if weekend else 7.0, 0.6)
        sleep_score = int(np.clip(45 + 5 * sleep_h + rng.normal(0, 6), 30, 98))
        hrv = float(np.clip(40 + 0.25 * sleep_score + rng.normal(0, 4) - 0.08 * prev_stress, 25, 95))
        bb_wake = int(np.clip(20 + 0.7 * sleep_score + rng.normal(0, 6), 5, 100))
        sleep_charge = int(np.clip(75 - 0.9 * prev_stress + rng.normal(0, 8), -5, 90))
        stress = int(np.clip(rng.normal(24 if weekend else 34, 7), 10, 80))
        moderate, vigorous = int(rng.integers(0, 50)), int(rng.integers(0, 25))
        session_load = float(rng.choice([0, 0, 60, 90, 140, 220]))
        acute = acute * (1 - 1 / 7) + session_load * 7 / 7
        chronic = chronic * (1 - 1 / 28) + session_load * 7 / 28
        vo2 += 0.002 * (session_load - 70) / 10 + rng.normal(0, 0.02)
        readiness = int(np.clip(0.5 * sleep_score + 0.4 * hrv - 0.05 * acute / 10 + rng.normal(0, 8), 1, 100))

        rows = {
            "daily_sleep": {"score": sleep_score, "duration_s": int(sleep_h * 3600),
                            "deep_s": int(sleep_h * 3600 * 0.2), "light_s": int(sleep_h * 3600 * 0.55),
                            "rem_s": int(sleep_h * 3600 * 0.2), "awake_s": int(rng.integers(300, 3000))},
            "daily_hrv": {"last_night_avg": round(hrv, 1), "weekly_avg": round(hrv, 1), "status": "BALANCED"},
            "daily_body_battery": {"at_wake": bb_wake, "highest": min(100, bb_wake + 3), "lowest": int(rng.integers(5, 30)),
                                   "charged": sleep_charge + 5, "drained": int(rng.integers(50, 90)),
                                   "sleep_charge": sleep_charge},
            "daily_stress": {"avg": stress, "max": min(99, stress + 50), "rest_s": 30000, "low_s": 15000,
                             "medium_s": 5000, "high_s": int(stress * 40)},
            "daily_rhr": {"resting_hr": int(np.clip(52 - 0.1 * (hrv - 55) + rng.normal(0, 1.5), 40, 70))},
            "daily_readiness": {"score": readiness, "recovery_time_min": int(rng.integers(0, 2400))},
            "daily_intensity": {"moderate_min": moderate, "vigorous_min": vigorous,
                                "total_min": moderate + 2 * vigorous, "weekly_goal": 150},
            "daily_training_load": {"acute_load": round(acute, 1), "chronic_load": round(chronic, 1),
                                    "acwr": round(acute / chronic, 2) if chronic else None,
                                    "focus_low_aerobic": 400.0, "focus_high_aerobic": 250.0, "focus_anaerobic": 60.0,
                                    "focus_low_aerobic_min": 300.0, "focus_low_aerobic_max": 600.0,
                                    "focus_high_aerobic_min": 200.0, "focus_high_aerobic_max": 450.0,
                                    "focus_anaerobic_min": 80.0, "focus_anaerobic_max": 200.0,
                                    "focus_feedback": "ANAEROBIC_SHORTAGE"},
            "daily_training_status": {"status_phrase": "PRODUCTIVE" if acute > chronic else "MAINTAINING"},
            "daily_respiration": {"sleep_avg": round(float(rng.normal(14, 0.6)), 1)},
            "daily_spo2": {"sleep_avg": round(float(rng.normal(95, 1)), 1)},
            "daily_hill": {"overall": 55.0 + i % 5},
            "daily_endurance": {"score": 6500.0 + rng.normal(0, 50), "granularity": "daily"},
        }
        for table, values in rows.items():
            repo.upsert_rows(conn, table, [{"date": iso, **values}])
        if i % 4 == 0:
            repo.upsert_rows(conn, "daily_vo2max", [{"date": iso, "running": round(vo2, 1)}])
        if session_load:
            repo.upsert_rows(conn, "activity", [{
                "activity_id": 10_000 + i, "date": iso, "start_local": f"{iso} 07:00:00",
                "type": "running" if i % 3 else "trail_running", "name": "Sortie",
                "duration_s": session_load * 30.0, "distance_m": session_load * 80.0,
                "elev_gain_m": session_load * 2.0, "avg_hr": 145.0, "max_hr": 172.0,
                "training_load": session_load, "aerobic_te": 3.2, "anaerobic_te": 1.1,
            }])
        prev_stress = stress
    for table in ("daily_sleep", "daily_hrv", "daily_body_battery", "activity"):
        repo.touch_availability(conn, table, [today.isoformat()])


def main() -> None:
    home = Path(sys.argv[1])
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    init_db(home / "recoveriq.db")
    with connect() as conn:
        populate(conn, days, date.today())
    print(f"Base de démonstration créée : {home / 'recoveriq.db'} ({days} jours)")


if __name__ == "__main__":
    main()
