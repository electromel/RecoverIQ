-- Migration 5 : FC moyenne et besoin de sommeil, meilleurs temps des activités, seuil lactique.
ALTER TABLE daily_sleep ADD COLUMN avg_hr REAL;               -- FC moyenne pendant le sommeil (bpm)
ALTER TABLE daily_sleep ADD COLUMN sleep_need_min INTEGER;    -- besoin de sommeil calculé par Garmin (min)
ALTER TABLE activity ADD COLUMN best_1k_s REAL;               -- meilleur temps sur 1 km pendant l'activité (s)
ALTER TABLE activity ADD COLUMN best_5k_s REAL;
ALTER TABLE activity ADD COLUMN best_10k_s REAL;

CREATE TABLE daily_lactate_threshold (
    date          TEXT PRIMARY KEY,   -- jour de la mesure (course)
    heart_rate    REAL,               -- FC au seuil (bpm)
    pace_s_per_km REAL,               -- allure au seuil (s/km)
    power         REAL                -- puissance au seuil (W)
);

-- Reprise des réponses Garmin déjà importées (aucun nouvel appel réseau).
INSERT INTO daily_sleep (date, avg_hr, sleep_need_min)
SELECT date, avg_hr, need FROM (
    SELECT r.start_date AS date,
           CASE WHEN json_extract(r.payload, '$.dailySleepDTO.avgHeartRate') > 0
                THEN json_extract(r.payload, '$.dailySleepDTO.avgHeartRate') END AS avg_hr,
           CASE WHEN json_extract(r.payload, '$.dailySleepDTO.sleepNeed.actual') > 0
                THEN CAST(json_extract(r.payload, '$.dailySleepDTO.sleepNeed.actual') AS INTEGER) END AS need
    FROM raw_response r
    WHERE r.fetcher = 'sleep' AND r.outcome = 'ok' AND json_valid(r.payload)
      AND json_type(r.payload) = 'object'
) WHERE avg_hr IS NOT NULL OR need IS NOT NULL
ON CONFLICT(date) DO UPDATE SET
    avg_hr = COALESCE(excluded.avg_hr, daily_sleep.avg_hr),
    sleep_need_min = COALESCE(excluded.sleep_need_min, daily_sleep.sleep_need_min);

CREATE TEMP TABLE _activity_best AS
SELECT json_extract(j.value, '$.activityId') AS activity_id,
       json_extract(j.value, '$.fastestSplit_1000') AS b1,
       json_extract(j.value, '$.fastestSplit_5000') AS b5,
       json_extract(j.value, '$.fastestSplit_10000') AS b10
FROM raw_response r,
     json_each(CASE WHEN json_valid(r.payload) AND json_type(r.payload) = 'array' THEN r.payload ELSE '[]' END) j
WHERE r.fetcher = 'activities' AND r.outcome = 'ok';

UPDATE activity SET
    best_1k_s = CASE WHEN b.b1 > 0 THEN b.b1 END,
    best_5k_s = CASE WHEN b.b5 > 0 THEN b.b5 END,
    best_10k_s = CASE WHEN b.b10 > 0 THEN b.b10 END
FROM _activity_best b WHERE b.activity_id = activity.activity_id;
DROP TABLE _activity_best;
