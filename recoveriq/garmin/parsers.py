"""Transformation des réponses JSON Garmin en lignes des tables normalisées.

Chaque parser reçoit la réponse brute et la date (ou la période) demandée, et
renvoie un dictionnaire ``{table: [lignes]}``. Règles communes :

* lecture strictement défensive (``_get``) : un champ absent donne ``None`` ;
* les valeurs sentinelles de Garmin (négatives pour « pas de mesure ») deviennent ``None`` ;
* une ligne ne contenant aucune mesure n'est pas émise.

Les noms de champs proviennent des réponses de Garmin Connect observées pour
garminconnect 0.3.2. Si Garmin les modifie, il suffit de corriger le parser et de
retraiter ``raw_response`` (aucun nouvel appel réseau nécessaire).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

Rows = dict[str, list[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _get(data: Any, *path: str | int) -> Any:
    """Accès imbriqué tolérant : _get(d, "a", "b", 0) ≈ d["a"]["b"][0] ou None."""
    cur = data
    for key in path:
        if isinstance(key, int):
            if not isinstance(cur, list) or len(cur) <= key:
                return None
        elif not isinstance(cur, dict):
            return None
        cur = cur[key] if isinstance(key, int) else cur.get(key)
        if cur is None:
            return None
    return cur


def _num(value: Any) -> float | None:
    """Nombre >= 0, sinon None (Garmin utilise -1 / -2 pour « pas de donnée »)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None else None


def _positive(value: Any) -> float | None:
    """Nombre > 0, sinon None (0 signifie « non mesuré » pour ces champs)."""
    number = _num(value)
    return number if number else None


def _str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _row(date: str, _meta: tuple[str, ...] = (), **values: Any) -> list[dict[str, Any]]:
    """Ligne journalière, ou liste vide si aucune mesure n'est renseignée.

    Les colonnes listées dans ``_meta`` (objectifs, moyennes glissantes, indicateurs
    techniques) sont conservées mais ne suffisent pas à rendre la ligne « non vide ».
    """
    if all(v is None for k, v in values.items() if k not in _meta):
        return []
    return [{"date": date, **values}]


def _primary_device_entry(device_map: Any) -> dict[str, Any] | None:
    """Garmin indexe certaines données par montre : on garde l'appareil d'entraînement principal."""
    if not isinstance(device_map, dict) or not device_map:
        return None
    entries = [v for v in device_map.values() if isinstance(v, dict)]
    for entry in entries:
        if entry.get("primaryTrainingDevice"):
            return entry
    return entries[0] if entries else None


def _phrase_label(phrase: Any) -> str | None:
    """'PRODUCTIVE_3' -> 'PRODUCTIVE' (le suffixe numérote seulement le message affiché)."""
    if not phrase:
        return None
    parts = str(phrase).split("_")
    return "_".join(parts[:-1]) if len(parts) > 1 and parts[-1].isdigit() else str(phrase)


# ---------------------------------------------------------------------------
# Appels journaliers
# ---------------------------------------------------------------------------

def parse_user_summary(payload: Any, date: str) -> Rows:
    """Résumé journalier : Body Battery, stress, intensité, FC repos, SpO2, respiration éveil."""
    p = payload if isinstance(payload, dict) else {}
    moderate = _int(p.get("moderateIntensityMinutes"))
    vigorous = _int(p.get("vigorousIntensityMinutes"))
    total = None if moderate is None and vigorous is None else (moderate or 0) + 2 * (vigorous or 0)
    return {
        "daily_body_battery": _row(
            date,
            highest=_int(p.get("bodyBatteryHighestValue")),
            lowest=_int(p.get("bodyBatteryLowestValue")),
            charged=_int(p.get("bodyBatteryChargedValue")),
            drained=_int(p.get("bodyBatteryDrainedValue")),
            at_wake=_int(p.get("bodyBatteryAtWakeTime")),
        ),
        "daily_stress": _row(
            date,
            avg=_int(p.get("averageStressLevel")),
            max=_int(p.get("maxStressLevel")),
            rest_s=_int(p.get("restStressDuration")),
            low_s=_int(p.get("lowStressDuration")),
            medium_s=_int(p.get("mediumStressDuration")),
            high_s=_int(p.get("highStressDuration")),
            activity_s=_int(p.get("activityStressDuration")),
            uncategorized_s=_int(p.get("uncategorizedStressDuration")),
        ),
        "daily_intensity": _row(
            date,
            _meta=("weekly_goal",),
            moderate_min=moderate,
            vigorous_min=vigorous,
            total_min=total,
            weekly_goal=_int(p.get("intensityMinutesGoal")),
        ),
        "daily_rhr": _row(
            date,
            _meta=("resting_hr_7d_avg",),
            resting_hr=_int(p.get("restingHeartRate")),
            resting_hr_7d_avg=_int(p.get("lastSevenDaysAvgRestingHeartRate")),
        ),
        "daily_spo2": _row(
            date,
            day_avg=_num(p.get("averageSpo2")),
            day_lowest=_num(p.get("lowestSpo2")),
        ),
        "daily_respiration": _row(date, waking_avg=_num(p.get("avgWakingRespirationValue"))),
    }


def parse_hrv(payload: Any, date: str) -> Rows:
    s = _get(payload, "hrvSummary")
    return {
        "daily_hrv": _row(
            date,
            last_night_avg=_num(_get(s, "lastNightAvg")),
            last_night_5min_high=_num(_get(s, "lastNight5MinHigh")),
            weekly_avg=_num(_get(s, "weeklyAvg")),
            baseline_low_upper=_num(_get(s, "baseline", "lowUpper")),
            baseline_balanced_low=_num(_get(s, "baseline", "balancedLow")),
            baseline_balanced_upper=_num(_get(s, "baseline", "balancedUpper")),
            status=_str(_get(s, "status")),
            feedback=_str(_get(s, "feedbackPhrase")),
        )
    }


# Tendance de forme (VO2 max) : codes Garmin → -1 baisse, 0 stable, +1 hausse (0 et 255 : non calculée).
_FITNESS_TREND = {1: -1, 2: 0, 3: 1}


def parse_training_status(payload: Any, date: str) -> Rows:
    """Statut, charge aiguë/chronique, ACWR, focus de charge et VO2 max."""
    status = _primary_device_entry(_get(payload, "mostRecentTrainingStatus", "latestTrainingStatusData"))
    acute = _get(status, "acuteTrainingLoadDTO")
    balance = _primary_device_entry(
        _get(payload, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap")
    )

    vo2_generic = _get(payload, "mostRecentVO2Max", "generic")
    vo2_cycling = _get(payload, "mostRecentVO2Max", "cycling")
    # La VO2 max est datée de sa propre mesure (souvent antérieure au jour demandé).
    vo2_rows: list[dict[str, Any]] = []
    for vo2, prefix in ((vo2_generic, "running"), (vo2_cycling, "cycling")):
        vo2_date = _str(_get(vo2, "calendarDate"))
        value = _num(_get(vo2, "vo2MaxValue"))
        if vo2_date and value is not None:
            vo2_rows.append({
                "date": vo2_date[:10],
                prefix: value,
                f"{prefix}_precise": _num(_get(vo2, "vo2MaxPreciseValue")),
            })

    acwr = _num(_get(acute, "dailyAcuteChronicWorkloadRatio"))
    # Nom des montres (la liste des activités ne donne que leur identifiant).
    recorded = _get(payload, "mostRecentTrainingStatus", "recordedDevices")
    devices = [
        {"device_id": d["deviceId"], "name": d["deviceName"], "date": date}
        for d in (recorded if isinstance(recorded, list) else [])
        if isinstance(d, dict) and isinstance(d.get("deviceId"), int) and not isinstance(d.get("deviceId"), bool)
        and isinstance(d.get("deviceName"), str) and d["deviceName"] and not d["deviceName"].startswith("other.")
    ]
    return {
        "device": devices,
        "daily_training_status": _row(
            date,
            _meta=("paused",),
            status_code=_int(_get(status, "trainingStatus")),
            status_phrase=_phrase_label(_get(status, "trainingStatusFeedbackPhrase")),
            weekly_load=_num(_get(status, "weeklyTrainingLoad")),
            load_tunnel_min=_num(_get(status, "loadTunnelMin")),
            load_tunnel_max=_num(_get(status, "loadTunnelMax")),
            load_trend=_get(status, "loadLevelTrend") if isinstance(_get(status, "loadLevelTrend"), int) else None,
            fitness_trend=_FITNESS_TREND.get(_get(status, "fitnessTrend")),
            paused=int(bool(_get(status, "trainingPaused"))) if status else None,
        ),
        "daily_training_load": _row(
            date,
            acute_load=_num(_get(acute, "dailyTrainingLoadAcute")),
            chronic_load=_num(_get(acute, "dailyTrainingLoadChronic")),
            chronic_min=_num(_get(acute, "minTrainingLoadChronic")),
            chronic_max=_num(_get(acute, "maxTrainingLoadChronic")),
            acwr=acwr,
            acwr_percent=_num(_get(acute, "acwrPercent")),
            acwr_status=_str(_get(acute, "acwrStatus")),
            focus_low_aerobic=_num(_get(balance, "monthlyLoadAerobicLow")),
            focus_high_aerobic=_num(_get(balance, "monthlyLoadAerobicHigh")),
            focus_anaerobic=_num(_get(balance, "monthlyLoadAnaerobic")),
            focus_low_aerobic_min=_num(_get(balance, "monthlyLoadAerobicLowTargetMin")),
            focus_low_aerobic_max=_num(_get(balance, "monthlyLoadAerobicLowTargetMax")),
            focus_high_aerobic_min=_num(_get(balance, "monthlyLoadAerobicHighTargetMin")),
            focus_high_aerobic_max=_num(_get(balance, "monthlyLoadAerobicHighTargetMax")),
            focus_anaerobic_min=_num(_get(balance, "monthlyLoadAnaerobicTargetMin")),
            focus_anaerobic_max=_num(_get(balance, "monthlyLoadAnaerobicTargetMax")),
            focus_feedback=_str(_get(balance, "trainingBalanceFeedbackPhrase")),
        ),
        "daily_vo2max": vo2_rows,
        # Anciennes montres : âge de forme fourni avec la VO2 max (les récentes passent par
        # le service dédié, voir parse_fitness_age).
        "daily_fitness_age": _row(date, fitness_age=_positive(_get(vo2_generic, "fitnessAge"))),
    }


def parse_sleep(payload: Any, date: str) -> Rows:
    """Sommeil + valeurs nocturnes (respiration, SpO2, recharge Body Battery)."""
    s = _get(payload, "dailySleepDTO")
    sleep_date = _str(_get(s, "calendarDate")) or date
    return {
        "daily_sleep": _row(
            sleep_date,
            score=_int(_get(s, "sleepScores", "overall", "value")),
            score_qualifier=_str(_get(s, "sleepScores", "overall", "qualifierKey")),
            duration_s=_int(_get(s, "sleepTimeSeconds")),
            deep_s=_int(_get(s, "deepSleepSeconds")),
            light_s=_int(_get(s, "lightSleepSeconds")),
            rem_s=_int(_get(s, "remSleepSeconds")),
            awake_s=_int(_get(s, "awakeSleepSeconds")),
            nap_s=_int(_get(s, "napTimeSeconds")),
            start_gmt=_epoch_ms_to_iso(_get(s, "sleepStartTimestampGMT")),
            end_gmt=_epoch_ms_to_iso(_get(s, "sleepEndTimestampGMT")),
            avg_sleep_stress=_num(_get(s, "avgSleepStress")),
            avg_overnight_hrv=_num(_get(payload, "avgOvernightHrv")),
            resting_hr=_int(_get(payload, "restingHeartRate")),
            avg_hr=_positive(_get(s, "avgHeartRate")),
            sleep_need_min=_int(_positive(_get(s, "sleepNeed", "actual"))),
        ),
        "daily_respiration": _row(
            sleep_date,
            sleep_avg=_num(_get(s, "averageRespirationValue")),
            sleep_min=_num(_get(s, "lowestRespirationValue")),
            sleep_max=_num(_get(s, "highestRespirationValue")),
        ),
        "daily_spo2": _row(
            sleep_date,
            sleep_avg=_num(_get(s, "averageSpO2Value")),
            sleep_lowest=_num(_get(s, "lowestSpO2Value")),
        ),
        "daily_body_battery": _row(sleep_date, sleep_charge=_bb_change(_get(payload, "bodyBatteryChange"))),
    }


def _bb_change(value: Any) -> int | None:
    # La variation nocturne peut être négative (nuit non récupératrice) : pas de filtre >= 0.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _epoch_ms_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _local_timestamp(value: Any) -> str | None:
    """'2026-11-17T17:34:30.0' → '2026-11-17 17:34:30' (même format que activity.start_local)."""
    text = _str(value)
    return text[:19].replace("T", " ") if text and len(text) >= 19 else None


def parse_training_readiness(payload: Any, date: str) -> Rows:
    """Plusieurs scores par jour : on garde celui du réveil et le dernier de la journée.

    Chaque relevé est aussi conservé dans ``readiness_event`` : celui qui suit une activité
    (AFTER_POST_EXERCISE_RESET) donne la durée de récupération après l'effort.
    """
    raw = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    raw = [e for e in raw if isinstance(e, dict)]
    events = [
        {"timestamp_local": ts, "date": date, "context": _str(e.get("inputContext")),
         "score": _int(e.get("score")), "recovery_time_min": _int(e.get("recoveryTime"))}
        for e in raw if (ts := _local_timestamp(e.get("timestampLocal")))
    ]
    entries = [e for e in raw if _num(e.get("score")) is not None]
    if not entries:
        return {"daily_readiness": [], "readiness_event": events}
    entries.sort(key=lambda e: str(e.get("timestamp") or e.get("timestampLocal") or ""))
    morning = next((e for e in entries if e.get("inputContext") == "AFTER_WAKEUP_RESET"), entries[0])
    latest = entries[-1]
    return {
        "daily_readiness": _row(
            date,
            score=_int(morning.get("score")),
            level=_str(morning.get("level")),
            feedback=_str(morning.get("feedbackShort")),
            recovery_time_min=_int(morning.get("recoveryTime")),
            sleep_factor_pct=_num(morning.get("sleepScoreFactorPercent")),
            recovery_factor_pct=_num(morning.get("recoveryTimeFactorPercent")),
            acwr_factor_pct=_num(morning.get("acwrFactorPercent")),
            hrv_factor_pct=_num(morning.get("hrvFactorPercent")),
            stress_history_factor_pct=_num(morning.get("stressHistoryFactorPercent")),
            sleep_history_factor_pct=_num(morning.get("sleepHistoryFactorPercent")),
            latest_score=_int(latest.get("score")),
            latest_recovery_time_min=_int(latest.get("recoveryTime")),
        ),
        "readiness_event": events,
    }


def parse_fitness_age(payload: Any, date: str) -> Rows:
    """Âge de forme physique (service Garmin dédié), arrondi au dixième d'année.

    Sans mesure récente (composantes « stale »), Garmin ne renvoie que l'âge réel :
    la journée est alors considérée vide.
    """
    def age(key: str) -> float | None:
        value = _positive(_get(payload, key))
        return round(value, 1) if value is not None else None

    return {"daily_fitness_age": _row(
        date, _meta=("chronological_age",),
        fitness_age=age("fitnessAge"),
        achievable_age=age("achievableFitnessAge"),
        chronological_age=_int(_get(payload, "chronologicalAge")),
    )}


def parse_endurance_day(payload: Any, date: str) -> Rows:
    return {
        "daily_endurance": _row(
            _str(_get(payload, "calendarDate")) or date,
            _meta=("granularity",),
            score=_num(_get(payload, "overallScore")),
            classification=_int(_get(payload, "classification")),
            granularity="daily",
        )
    }


# ---------------------------------------------------------------------------
# Appels par plage de dates
# ---------------------------------------------------------------------------

def parse_body_battery_range(payload: Any, start: str, end: str) -> Rows:
    rows: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        day = _str(_get(item, "date"))
        if not day:
            continue
        levels = [
            _num(v[1]) for v in (_get(item, "bodyBatteryValuesArray") or [])
            if isinstance(v, list) and len(v) > 1 and _num(v[1]) is not None
        ]
        rows += _row(
            day[:10],
            charged=_int(_get(item, "charged")),
            drained=_int(_get(item, "drained")),
            highest=_int(max(levels)) if levels else None,
            lowest=_int(min(levels)) if levels else None,
        )
    return {"daily_body_battery": rows}


def parse_hill_range(payload: Any, start: str, end: str) -> Rows:
    rows: list[dict[str, Any]] = []
    for item in _get(payload, "hillScoreDTOList") or []:
        day = _str(_get(item, "calendarDate"))
        if day:
            rows += _row(
                day[:10],
                overall=_num(_get(item, "overallScore")),
                strength=_num(_get(item, "strengthScore")),
                endurance=_num(_get(item, "enduranceScore")),
            )
    return {"daily_hill": rows}


def parse_endurance_range(payload: Any, start: str, end: str) -> Rows:
    """Import historique : Garmin ne fournit sur une plage que des moyennes hebdomadaires."""
    rows: list[dict[str, Any]] = []
    group_map = _get(payload, "groupMap")
    if isinstance(group_map, dict):
        for week_start, group in group_map.items():
            score = _num(_get(group, "groupAverage"))
            if score is not None:
                rows.append({"date": str(week_start)[:10], "score": score, "granularity": "weekly"})
    return {"daily_endurance": rows}


def parse_activities(payload: Any, start: str, end: str) -> Rows:
    rows: list[dict[str, Any]] = []
    for a in payload if isinstance(payload, list) else []:
        activity_id = _get(a, "activityId")
        start_local = _str(_get(a, "startTimeLocal"))
        if not isinstance(activity_id, int) or not start_local:
            continue
        rows.append({
            "activity_id": activity_id,
            "device_id": _int(_get(a, "deviceId")),
            "date": start_local[:10],
            "start_local": start_local,
            "type": _str(_get(a, "activityType", "typeKey")),
            "name": _str(_get(a, "activityName")),
            "duration_s": _num(_get(a, "duration")),
            "moving_s": _num(_get(a, "movingDuration")),
            "distance_m": _num(_get(a, "distance")),
            "elev_gain_m": _num(_get(a, "elevationGain")),
            "elev_loss_m": _num(_get(a, "elevationLoss")),
            "avg_hr": _num(_get(a, "averageHR")),
            "max_hr": _num(_get(a, "maxHR")),
            "calories": _num(_get(a, "calories")),
            "training_load": _num(_get(a, "activityTrainingLoad")),
            "aerobic_te": _num(_get(a, "aerobicTrainingEffect")),
            "anaerobic_te": _num(_get(a, "anaerobicTrainingEffect")),
            "vo2max": _num(_get(a, "vO2MaxValue")),
            "best_1k_s": _positive(_get(a, "fastestSplit_1000")),
            "best_5k_s": _positive(_get(a, "fastestSplit_5000")),
            "best_10k_s": _positive(_get(a, "fastestSplit_10000")),
        })
    return {"activity": rows}


def parse_lactate_threshold(payload: Any, start: str, end: str) -> Rows:
    """Seuil lactique de course : FC, vitesse et puissance, chacune datée de sa mesure.

    Garmin exprime la vitesse en dixièmes de mètre par seconde (0,2944 → 2,944 m/s,
    soit 5:40 / km) : elle est convertie en allure (secondes par kilomètre).
    """
    by_date: dict[str, dict[str, Any]] = {}

    def collect(items: Any, column: str, convert: Callable[[float], float]) -> None:
        for item in items if isinstance(items, list) else []:
            day = _str(_get(item, "from"))
            value = _positive(_get(item, "value"))
            if day and value is not None:
                by_date.setdefault(day[:10], {"date": day[:10]})[column] = round(convert(value), 1)

    collect(_get(payload, "heart_rate"), "heart_rate", lambda v: v)
    collect(_get(payload, "speed"), "pace_s_per_km", lambda v: 1000 / (v * 10))
    collect(_get(payload, "power"), "power", lambda v: v)
    return {"daily_lactate_threshold": [by_date[d] for d in sorted(by_date)]}


def no_rows(payload: Any, date: str) -> Rows:
    """Appel conservé uniquement en brut (détail intra-journalier)."""
    return {}


def has_values(payload: Any, key: str) -> bool:
    """Vrai si la liste ``payload[key]`` contient au moins une mesure."""
    return isinstance(payload, dict) and isinstance(payload.get(key), list) and bool(payload[key])


DailyParser = Callable[[Any, str], Rows]
RangeParser = Callable[[Any, str, str], Rows]
