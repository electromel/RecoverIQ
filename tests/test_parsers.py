"""Parsers : extraction correcte, tolérance aux champs absents et aux sentinelles."""

from recoveriq.garmin import parsers

D = "2026-11-10"


def test_user_summary_extracts_and_filters_sentinels():
    rows = parsers.parse_user_summary({
        "bodyBatteryHighestValue": 88, "bodyBatteryLowestValue": 12,
        "bodyBatteryChargedValue": 60, "bodyBatteryDrainedValue": 70, "bodyBatteryAtWakeTime": 80,
        "averageStressLevel": -1, "maxStressLevel": 90, "restStressDuration": 30000,
        "moderateIntensityMinutes": 20, "vigorousIntensityMinutes": 10, "intensityMinutesGoal": 150,
        "restingHeartRate": 48, "averageSpo2": 96.0, "avgWakingRespirationValue": 14.0,
    }, D)
    assert rows["daily_body_battery"] == [{"date": D, "highest": 88, "lowest": 12, "charged": 60,
                                           "drained": 70, "at_wake": 80}]
    assert rows["daily_stress"][0]["avg"] is None          # -1 = pas de mesure
    assert rows["daily_stress"][0]["max"] == 90
    assert rows["daily_intensity"][0]["total_min"] == 40   # 20 + 2 x 10
    assert rows["daily_rhr"][0]["resting_hr"] == 48


def test_user_summary_goal_alone_is_not_data():
    rows = parsers.parse_user_summary({"intensityMinutesGoal": 150}, D)
    assert all(not r for r in rows.values())


def test_empty_payloads_never_raise():
    for parser in (parsers.parse_user_summary, parsers.parse_hrv, parsers.parse_training_status,
                   parsers.parse_sleep, parsers.parse_training_readiness, parsers.parse_endurance_day):
        for payload in ({}, [], None, "x"):
            result = parser(payload, D)
            assert all(not rows for rows in result.values())
    for parser in (parsers.parse_body_battery_range, parsers.parse_hill_range,
                   parsers.parse_endurance_range, parsers.parse_activities):
        for payload in ({}, [], None):
            assert all(not rows for rows in parser(payload, D, D).values())


def test_hrv():
    rows = parsers.parse_hrv({"hrvSummary": {
        "lastNightAvg": 55, "weeklyAvg": 58, "status": "BALANCED",
        "baseline": {"balancedLow": 50, "balancedUpper": 65},
    }}, D)["daily_hrv"][0]
    assert rows["last_night_avg"] == 55 and rows["baseline_balanced_upper"] == 65
    assert rows["status"] == "BALANCED"


def test_training_status_picks_primary_device_and_dates_vo2max():
    payload = {
        "mostRecentVO2Max": {"generic": {"calendarDate": "2026-11-08", "vo2MaxValue": 52, "vo2MaxPreciseValue": 52.4}},
        "mostRecentTrainingStatus": {"latestTrainingStatusData": {
            "1": {"trainingStatus": 2, "trainingStatusFeedbackPhrase": "MAINTAINING_1"},
            "2": {"primaryTrainingDevice": True, "trainingStatus": 7,
                  "trainingStatusFeedbackPhrase": "PRODUCTIVE_3", "weeklyTrainingLoad": 420,
                  "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 500, "dailyTrainingLoadChronic": 400,
                                           "dailyAcuteChronicWorkloadRatio": 1.25, "acwrStatus": "OPTIMAL"}},
        }},
        "mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {
            "2": {"primaryTrainingDevice": True, "monthlyLoadAerobicLow": 300, "monthlyLoadAnaerobic": 80},
        }},
    }
    rows = parsers.parse_training_status(payload, D)
    status = rows["daily_training_status"][0]
    assert status["status_code"] == 7 and status["status_phrase"] == "PRODUCTIVE"
    load = rows["daily_training_load"][0]
    assert load["acwr"] == 1.25 and load["focus_low_aerobic"] == 300 and load["focus_anaerobic"] == 80
    assert rows["daily_vo2max"] == [{"date": "2026-11-08", "running": 52.0, "running_precise": 52.4}]


def test_sleep_and_nocturnal_values():
    rows = parsers.parse_sleep({
        "dailySleepDTO": {"calendarDate": D, "sleepTimeSeconds": 27000, "deepSleepSeconds": 5400,
                          "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
                          "averageRespirationValue": 13.5, "averageSpO2Value": 95.0,
                          "sleepStartTimestampGMT": 1_762_732_800_000},
        "bodyBatteryChange": -3, "avgOvernightHrv": 57.0,
    }, D)
    assert rows["daily_sleep"][0]["score"] == 82
    assert rows["daily_sleep"][0]["start_gmt"].startswith("2025-11-10")
    assert rows["daily_respiration"][0]["sleep_avg"] == 13.5
    assert rows["daily_spo2"][0]["sleep_avg"] == 95.0
    assert rows["daily_body_battery"][0]["sleep_charge"] == -3   # négatif conservé


def test_readiness_morning_and_latest():
    rows = parsers.parse_training_readiness([
        {"timestamp": "2026-11-10T18:00:00", "score": 40, "recoveryTime": 900},
        {"timestamp": "2026-11-10T06:30:00", "score": 75, "level": "HIGH", "recoveryTime": 120,
         "inputContext": "AFTER_WAKEUP_RESET"},
    ], D)["daily_readiness"][0]
    assert rows["score"] == 75 and rows["recovery_time_min"] == 120
    assert rows["latest_score"] == 40 and rows["latest_recovery_time_min"] == 900


def test_readiness_events_keep_every_entry():
    events = parsers.parse_training_readiness([
        {"timestampLocal": "2026-11-10T17:34:30.0", "score": 77, "recoveryTime": 1457,
         "inputContext": "AFTER_POST_EXERCISE_RESET"},
        {"timestampLocal": "2026-11-10T07:37:25.0", "score": 97, "recoveryTime": -1,
         "inputContext": "AFTER_WAKEUP_RESET"},
        {"score": 50},   # sans horodatage : ignoré
    ], D)["readiness_event"]
    assert events == [
        {"timestamp_local": "2026-11-10 17:34:30", "date": D, "context": "AFTER_POST_EXERCISE_RESET",
         "score": 77, "recovery_time_min": 1457},
        {"timestamp_local": "2026-11-10 07:37:25", "date": D, "context": "AFTER_WAKEUP_RESET",
         "score": 97, "recovery_time_min": None},
    ]


def test_ranges():
    bb = parsers.parse_body_battery_range(
        [{"date": D, "charged": 50, "drained": 60, "bodyBatteryValuesArray": [[1, 20], [2, 85], [3, None]]}], D, D)
    assert bb["daily_body_battery"][0] == {"date": D, "charged": 50, "drained": 60, "highest": 85, "lowest": 20}

    hill = parsers.parse_hill_range({"hillScoreDTOList": [{"calendarDate": D, "overallScore": 60}]}, D, D)
    assert hill["daily_hill"][0]["overall"] == 60

    endurance = parsers.parse_endurance_range({"groupMap": {"2026-11-03": {"groupAverage": 6500}}}, D, D)
    assert endurance["daily_endurance"] == [{"date": "2026-11-03", "score": 6500, "granularity": "weekly"}]

    acts = parsers.parse_activities([{
        "activityId": 123, "startTimeLocal": "2026-11-10 07:00:00", "activityType": {"typeKey": "running"},
        "duration": 3600.0, "distance": 10000.0, "elevationGain": 120.0, "averageHR": 145.0,
        "activityTrainingLoad": 110.0,
    }, {"activityId": None}], D, D)["activity"]
    assert len(acts) == 1 and acts[0]["type"] == "running" and acts[0]["date"] == D


def test_devices_from_training_status_and_activities():
    rows = parsers.parse_training_status({"mostRecentTrainingStatus": {"recordedDevices": [
        {"deviceId": 348, "deviceName": "Forerunner 955 Solar"},
        {"deviceId": 398, "deviceName": "other.device"},   # nom générique : ignoré
        {"deviceName": "sans identifiant"},
    ]}}, D)
    assert rows["device"] == [{"device_id": 348, "name": "Forerunner 955 Solar", "date": D}]
    acts = parsers.parse_activities([
        {"activityId": 1, "startTimeLocal": f"{D} 10:00:00", "deviceId": 348},
        {"activityId": 2, "startTimeLocal": f"{D} 12:00:00"},
    ], D, D)["activity"]
    assert [a["device_id"] for a in acts] == [348, None]



def test_sleep_heart_rate_and_need():
    rows = parsers.parse_sleep({"dailySleepDTO": {"sleepTimeSeconds": 25980, "avgHeartRate": 59.0,
                                                  "sleepNeed": {"baseline": 460, "actual": 420}}}, D)
    assert rows["daily_sleep"][0]["avg_hr"] == 59.0 and rows["daily_sleep"][0]["sleep_need_min"] == 420


def test_activity_best_times():
    act = parsers.parse_activities([{"activityId": 1, "startTimeLocal": f"{D} 10:00:00", "fastestSplit_1000": 409.69,
                                     "fastestSplit_5000": 2224.9, "fastestSplit_10000": None}], D, D)["activity"][0]
    assert (act["best_1k_s"], act["best_5k_s"], act["best_10k_s"]) == (409.69, 2224.9, None)


def test_lactate_threshold():
    rows = parsers.parse_lactate_threshold({
        "speed": [{"from": "2025-01-01", "value": 0.31666578}, {"from": "2025-01-05", "value": 0}],
        "heart_rate": [{"from": "2025-01-01", "value": 168.0}, {"from": "2024-09-12", "value": 158.0}],
        "power": [{"from": "2025-01-01", "value": 316.0}],
    }, "2024-09-01", "2025-01-31")["daily_lactate_threshold"]
    assert rows == [
        {"date": "2024-09-12", "heart_rate": 158.0},
        {"date": "2025-01-01", "heart_rate": 168.0, "pace_s_per_km": 315.8, "power": 316.0},   # 5:16 / km
    ]
    assert parsers.parse_lactate_threshold(None, "2024-09-01", "2024-09-30") == {"daily_lactate_threshold": []}
