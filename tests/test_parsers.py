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
