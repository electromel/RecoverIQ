-- Schéma RecoverIQ, version 1.
-- Les colonnes de mesure sont toutes nullables : une donnée non fournie par la montre reste NULL.
-- Dates au format ISO 'YYYY-MM-DD' (jour calendaire local Garmin), horodatages en ISO 8601 UTC.

-- ---------------------------------------------------------------------------
-- Pilotage : brut, reprise, disponibilité, journal
-- ---------------------------------------------------------------------------

-- Dernière réponse brute reçue pour (fetcher, période). Permet de retraiter sans rappeler Garmin.
CREATE TABLE raw_response (
    fetcher     TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK (outcome IN ('ok', 'empty', 'unsupported', 'error')),
    http_status INTEGER,
    payload     TEXT,               -- JSON brut tel que renvoyé par Garmin
    error       TEXT,
    PRIMARY KEY (fetcher, start_date, end_date)
);

-- Avancement de l'import historique, pour la reprise après interruption.
CREATE TABLE import_progress (
    fetcher     TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('done', 'error', 'skipped')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (fetcher, start_date)
);

-- Un indicateur est « disponible » dès qu'au moins une valeur non nulle a été reçue.
CREATE TABLE metric_availability (
    metric       TEXT PRIMARY KEY,  -- nom de la table normalisée
    first_seen   TEXT,              -- plus ancienne date avec donnée
    last_seen    TEXT,              -- plus récente date avec donnée
    last_checked TEXT NOT NULL
);

CREATE TABLE sync_run (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL CHECK (kind IN ('backfill', 'incremental')),
    trigger        TEXT NOT NULL,   -- 'scheduler', 'manual', 'startup', 'login'
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed', 'interrupted')),
    days_processed INTEGER NOT NULL DEFAULT 0,
    api_calls      INTEGER NOT NULL DEFAULT 0,
    errors_count   INTEGER NOT NULL DEFAULT 0,
    message        TEXT
);

CREATE TABLE sync_error (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL REFERENCES sync_run(id) ON DELETE CASCADE,
    fetcher     TEXT NOT NULL,
    date        TEXT NOT NULL,
    message     TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX ix_sync_error_run ON sync_error(sync_run_id);

-- Paramètres non secrets (clé / valeur JSON).
CREATE TABLE app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------------
-- Tables normalisées : une ligne par jour
-- ---------------------------------------------------------------------------

CREATE TABLE daily_body_battery (
    date          TEXT PRIMARY KEY,
    highest       INTEGER,
    lowest        INTEGER,
    charged       INTEGER,   -- recharge totale de la journée
    drained       INTEGER,   -- décharge totale de la journée
    at_wake       INTEGER,   -- niveau au réveil
    sleep_charge  INTEGER    -- variation pendant la nuit se terminant ce jour-là
);

CREATE TABLE daily_hrv (
    date                    TEXT PRIMARY KEY,
    last_night_avg          REAL,   -- ms
    last_night_5min_high    REAL,
    weekly_avg              REAL,
    baseline_low_upper      REAL,
    baseline_balanced_low   REAL,
    baseline_balanced_upper REAL,
    status                  TEXT,   -- BALANCED, UNBALANCED, LOW, POOR, NONE
    feedback                TEXT
);

CREATE TABLE daily_training_load (
    date                 TEXT PRIMARY KEY,
    acute_load           REAL,
    chronic_load         REAL,
    chronic_min          REAL,     -- bornes de la zone optimale de charge chronique
    chronic_max          REAL,
    acwr                 REAL,     -- ratio aiguë / chronique
    acwr_percent         REAL,
    acwr_status          TEXT,     -- LOW, OPTIMAL, HIGH, VERY_HIGH
    focus_low_aerobic    REAL,     -- charges sur 4 semaines par focus
    focus_high_aerobic   REAL,
    focus_anaerobic      REAL,
    focus_low_aerobic_min  REAL, focus_low_aerobic_max  REAL,
    focus_high_aerobic_min REAL, focus_high_aerobic_max REAL,
    focus_anaerobic_min    REAL, focus_anaerobic_max    REAL,
    focus_feedback       TEXT
);

CREATE TABLE daily_training_status (
    date            TEXT PRIMARY KEY,
    status_code     INTEGER,
    status_phrase   TEXT,   -- ex. PRODUCTIVE, MAINTAINING, RECOVERY, UNPRODUCTIVE...
    weekly_load     REAL,
    load_tunnel_min REAL,
    load_tunnel_max REAL,
    load_trend      INTEGER,
    fitness_trend   INTEGER,
    paused          INTEGER
);

CREATE TABLE daily_intensity (
    date         TEXT PRIMARY KEY,
    moderate_min INTEGER,
    vigorous_min INTEGER,
    total_min    INTEGER,   -- modérées + 2 x intenses (convention Garmin)
    weekly_goal  INTEGER
);

CREATE TABLE daily_vo2max (
    date             TEXT PRIMARY KEY,   -- date de la mesure VO2 max
    running          REAL,
    running_precise  REAL,
    cycling          REAL,
    cycling_precise  REAL,
    fitness_age      REAL
);

CREATE TABLE daily_stress (
    date             TEXT PRIMARY KEY,
    avg              INTEGER,
    max              INTEGER,
    rest_s           INTEGER,
    low_s            INTEGER,
    medium_s         INTEGER,
    high_s           INTEGER,
    activity_s       INTEGER,
    uncategorized_s  INTEGER
);

CREATE TABLE daily_sleep (
    date                TEXT PRIMARY KEY,   -- jour du réveil
    score               INTEGER,
    score_qualifier     TEXT,
    duration_s          INTEGER,
    deep_s              INTEGER,
    light_s             INTEGER,
    rem_s               INTEGER,
    awake_s             INTEGER,
    nap_s               INTEGER,
    start_gmt           TEXT,
    end_gmt             TEXT,
    avg_sleep_stress    REAL,
    avg_overnight_hrv   REAL,
    resting_hr          INTEGER
);

CREATE TABLE daily_rhr (
    date        TEXT PRIMARY KEY,
    resting_hr  INTEGER,
    resting_hr_7d_avg INTEGER
);

CREATE TABLE daily_readiness (
    date                      TEXT PRIMARY KEY,
    score                     INTEGER,   -- score du matin (après réveil)
    level                     TEXT,
    feedback                  TEXT,
    recovery_time_min         INTEGER,   -- temps de récupération au moment du score du matin
    sleep_factor_pct          REAL,
    recovery_factor_pct       REAL,
    acwr_factor_pct           REAL,
    hrv_factor_pct            REAL,
    stress_history_factor_pct REAL,
    sleep_history_factor_pct  REAL,
    latest_score              INTEGER,   -- dernier score de la journée
    latest_recovery_time_min  INTEGER
);

CREATE TABLE daily_endurance (
    date           TEXT PRIMARY KEY,
    score          REAL,
    classification INTEGER,
    granularity    TEXT    -- 'daily' (valeur exacte) ou 'weekly' (moyenne hebdo, import historique)
);

CREATE TABLE daily_hill (
    date      TEXT PRIMARY KEY,
    overall   REAL,
    strength  REAL,
    endurance REAL
);

CREATE TABLE daily_respiration (
    date       TEXT PRIMARY KEY,
    sleep_avg  REAL,   -- respirations / min pendant le sommeil
    sleep_min  REAL,
    sleep_max  REAL,
    waking_avg REAL
);

CREATE TABLE daily_spo2 (
    date         TEXT PRIMARY KEY,
    sleep_avg    REAL,   -- %
    sleep_lowest REAL,
    day_avg      REAL,
    day_lowest   REAL
);

CREATE TABLE activity (
    activity_id   INTEGER PRIMARY KEY,
    date          TEXT NOT NULL,
    start_local   TEXT,
    type          TEXT,
    name          TEXT,
    duration_s    REAL,
    moving_s      REAL,
    distance_m    REAL,
    elev_gain_m   REAL,
    elev_loss_m   REAL,
    avg_hr        REAL,
    max_hr        REAL,
    calories      REAL,
    training_load REAL,
    aerobic_te    REAL,
    anaerobic_te  REAL,
    vo2max        REAL
);
CREATE INDEX ix_activity_date ON activity(date);
