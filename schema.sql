-- HiScribe shared SQLite schema
-- Both gateway (Node) and pipeline (Python) read/write this DB
-- Append-only rule: audit_log never receives UPDATE or DELETE

CREATE TABLE IF NOT EXISTS sessions (
  id                    TEXT PRIMARY KEY,
  status                TEXT NOT NULL DEFAULT 'recording',
  provider_id           TEXT,
  provider_npi          TEXT,
  patient_mrn           TEXT,
  visit_type            TEXT,
  asr_engine            TEXT DEFAULT 'gladia',
  diarization_engine    TEXT DEFAULT 'pyannote',
  llm_model             TEXT DEFAULT 'gpt-4o-mini',
  language              TEXT DEFAULT 'en',
  segment_count         INTEGER DEFAULT 0,
  flagged_segment_count INTEGER DEFAULT 0,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at              TEXT,
  approved_at           TEXT
);

CREATE TABLE IF NOT EXISTS segments (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  segment_id        TEXT NOT NULL DEFAULT (lower(hex(randomblob(8)))),
  session_id        TEXT NOT NULL,
  text              TEXT NOT NULL,
  speaker           TEXT NOT NULL DEFAULT 'UNKNOWN',
  soap_section      TEXT,
  start_ms          INTEGER NOT NULL DEFAULT 0,
  end_ms            INTEGER NOT NULL DEFAULT 0,
  confidence        REAL NOT NULL DEFAULT 1.0,
  reliability_score REAL,
  role_flag         INTEGER DEFAULT 0,
  confidence_flag   INTEGER DEFAULT 0,
  is_final          INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS amendments (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  soap_section TEXT NOT NULL,
  content      TEXT NOT NULL,
  provider_id  TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- append-only: no UPDATE or DELETE ever runs on this table
CREATE TABLE IF NOT EXISTS audit_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  segment_id   TEXT,
  provider_id  TEXT,
  payload      TEXT NOT NULL,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS provider_enrollments (
  provider_id         TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  encrypted_embedding BLOB NOT NULL,
  quality_score       REAL NOT NULL,
  sample_count        INTEGER NOT NULL,
  enrolled_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- FHIR bundles generated on approval. One row per session; re-emission replaces
-- it, since the bundle is derived state that can always be rebuilt from
-- sessions + segments + amendments. This is NOT an audit record — the audit
-- trail lives in audit_log and stays append-only.
CREATE TABLE IF NOT EXISTS fhir_bundles (
  session_id   TEXT PRIMARY KEY,
  bundle_json  TEXT NOT NULL,
  fhir_version TEXT NOT NULL DEFAULT 'R4B',
  status       TEXT NOT NULL DEFAULT 'generated',
  destination  TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Indexes on hot-path queries
-- segments: pipeline reads final segments per session on every pipeline run
CREATE INDEX IF NOT EXISTS idx_segments_session_final
  ON segments(session_id, is_final);

-- audit_log: training data query filters by event_type and session_id
CREATE INDEX IF NOT EXISTS idx_audit_log_event_session
  ON audit_log(event_type, session_id);
