-- Migration 2 : archivage des analyses IA (étape 3).
CREATE TABLE ai_report (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    finished_at       TEXT,
    trigger           TEXT NOT NULL,              -- 'manual' | 'scheduler'
    period_start      TEXT NOT NULL,
    period_end        TEXT NOT NULL,
    period_days       INTEGER NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    summary_json      TEXT,                       -- résumé agrégé effectivement envoyé
    comparison_json   TEXT,                       -- comparaison déterministe
    synthesis_json    TEXT,                       -- synthèse de l'agrégateur (si réussie)
    synthesis_mode    TEXT,                       -- 'single' | 'llm' | 'fallback'
    aggregator        TEXT,
    aggregator_model  TEXT,
    aggregator_error  TEXT,
    aggregator_cost   REAL,
    total_cost        REAL,                       -- USD, estimation (NULL si tarifs inconnus)
    cost_complete     INTEGER NOT NULL DEFAULT 1, -- 0 si un tarif manquait
    error             TEXT
);
CREATE INDEX ix_ai_report_created ON ai_report(created_at);

CREATE TABLE ai_provider_result (
    report_id      INTEGER NOT NULL REFERENCES ai_report(id) ON DELETE CASCADE,
    provider       TEXT NOT NULL,
    model          TEXT,
    status         TEXT NOT NULL CHECK (status IN ('ok', 'error', 'timeout', 'invalid')),
    duration_ms    INTEGER,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost           REAL,
    report_json    TEXT,                          -- rapport validé
    warnings       TEXT,                          -- JSON : écarts de format corrigés
    raw_text       TEXT,                          -- réponse brute (diagnostic)
    error          TEXT,
    PRIMARY KEY (report_id, provider)
);
