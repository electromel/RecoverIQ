-- Migration 4 : montre de chaque activité et nom des modèles.
ALTER TABLE activity ADD COLUMN device_id INTEGER;   -- deviceId Garmin (0 : aucune montre)

-- Nom des montres, tiré des réponses « statut d'entraînement » (recordedDevices).
-- date : jour où ce nom a été vu ; le nom le plus récent l'emporte.
CREATE TABLE device (
    device_id INTEGER PRIMARY KEY,
    name      TEXT,
    date      TEXT NOT NULL
);

-- Reprise des réponses Garmin déjà importées (aucun nouvel appel réseau).
CREATE TEMP TABLE _activity_device AS
SELECT json_extract(j.value, '$.activityId') AS activity_id,
       json_extract(j.value, '$.deviceId') AS device_id
FROM raw_response r,
     json_each(CASE WHEN json_valid(r.payload) AND json_type(r.payload) = 'array' THEN r.payload ELSE '[]' END) j
WHERE r.fetcher = 'activities' AND r.outcome = 'ok'
  AND json_type(j.value, '$.deviceId') = 'integer';

UPDATE activity SET device_id = d.device_id
FROM _activity_device d WHERE d.activity_id = activity.activity_id;
DROP TABLE _activity_device;

INSERT INTO device (device_id, name, date)
SELECT device_id, name, date FROM (
    SELECT json_extract(d.value, '$.deviceId') AS device_id,
           json_extract(d.value, '$.deviceName') AS name,
           r.start_date AS date,
           ROW_NUMBER() OVER (PARTITION BY json_extract(d.value, '$.deviceId') ORDER BY r.start_date DESC) AS rn
    FROM raw_response r,
         json_each(CASE WHEN json_valid(r.payload) THEN
             COALESCE(json_extract(r.payload, '$.mostRecentTrainingStatus.recordedDevices'), '[]') ELSE '[]' END) d
    WHERE r.fetcher = 'training_status' AND r.outcome = 'ok'
      AND json_type(d.value, '$.deviceId') = 'integer'
      AND json_type(d.value, '$.deviceName') = 'text'
      AND json_extract(d.value, '$.deviceName') NOT LIKE 'other.%'
) WHERE rn = 1;
