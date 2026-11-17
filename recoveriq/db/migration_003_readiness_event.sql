-- Migration 3 : relevés Training Readiness horodatés (plusieurs par jour).
-- Le relevé AFTER_POST_EXERCISE_RESET suit chaque activité et donne la durée de
-- récupération estimée après l'effort.
CREATE TABLE readiness_event (
    timestamp_local   TEXT PRIMARY KEY,   -- 'YYYY-MM-DD HH:MM:SS', heure locale
    date              TEXT NOT NULL,
    context           TEXT,               -- AFTER_WAKEUP_RESET, AFTER_POST_EXERCISE_RESET...
    score             INTEGER,
    recovery_time_min INTEGER
);
CREATE INDEX ix_readiness_event_date ON readiness_event(date);

-- Reprise des réponses Garmin déjà importées (aucun nouvel appel réseau).
INSERT OR REPLACE INTO readiness_event (timestamp_local, date, context, score, recovery_time_min)
SELECT replace(substr(json_extract(j.value, '$.timestampLocal'), 1, 19), 'T', ' '),
       r.start_date,
       json_extract(j.value, '$.inputContext'),
       CASE WHEN json_extract(j.value, '$.score') >= 0
            THEN CAST(round(json_extract(j.value, '$.score')) AS INTEGER) END,
       CASE WHEN json_extract(j.value, '$.recoveryTime') >= 0
            THEN CAST(round(json_extract(j.value, '$.recoveryTime')) AS INTEGER) END
FROM raw_response r,
     json_each(CASE
         WHEN NOT json_valid(r.payload) THEN '[]'
         WHEN json_type(r.payload) = 'object' THEN json_array(json(r.payload))
         WHEN json_type(r.payload) = 'array' THEN r.payload
         ELSE '[]' END) j
WHERE r.fetcher = 'training_readiness' AND r.outcome = 'ok'
  AND json_type(j.value) = 'object'
  AND json_extract(j.value, '$.timestampLocal') IS NOT NULL;
