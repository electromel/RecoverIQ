-- Migration 6 : âge de forme physique, tendance de forme exprimée en -1 / 0 / +1.
CREATE TABLE daily_fitness_age (
    date              TEXT PRIMARY KEY,
    fitness_age       REAL,      -- âge de forme physique (ans)
    achievable_age    REAL,      -- âge de forme atteignable selon Garmin (ans)
    chronological_age INTEGER    -- âge réel à la date (ans)
);

-- Tendance de forme (VO2 max) : codes Garmin 1 = baisse, 2 = stable, 3 = hausse ;
-- 0 et 255 = non calculée.
UPDATE daily_training_status SET fitness_trend = CASE fitness_trend
    WHEN 1 THEN -1 WHEN 2 THEN 0 WHEN 3 THEN 1 END;

-- Anciennes montres : l'âge de forme figurait dans le statut d'entraînement (VO2 max).
-- Reprise des réponses déjà importées (aucun nouvel appel réseau).
INSERT INTO daily_fitness_age (date, fitness_age)
SELECT r.start_date, json_extract(r.payload, '$.mostRecentVO2Max.generic.fitnessAge')
FROM raw_response r
WHERE r.fetcher = 'training_status' AND r.outcome = 'ok' AND json_valid(r.payload)
  AND json_type(r.payload) = 'object'
  AND json_extract(r.payload, '$.mostRecentVO2Max.generic.fitnessAge') > 0
ON CONFLICT(date) DO UPDATE SET fitness_age = COALESCE(daily_fitness_age.fitness_age, excluded.fitness_age);
