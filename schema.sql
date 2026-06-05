-- Sailing Coach database schema (SQLite)
-- One row per training/racing session, plus a downsampled time-series for detail.

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT UNIQUE NOT NULL,      -- prevents duplicate imports on re-run
    sport           TEXT,                      -- cycling | sailing | strength | other
    sub_sport       TEXT,
    is_race         INTEGER DEFAULT 0,         -- 1 = regatta/competition (set by user or filename tag)
    start_time      TEXT,                      -- ISO timestamp
    duration_s      REAL,
    distance_m      REAL,
    avg_hr          REAL,
    max_hr          REAL,
    avg_power       REAL,                       -- cycling
    max_power       REAL,                       -- cycling
    normalized_power REAL,                      -- cycling (NP)
    efficiency_factor REAL,                     -- NP / avg_hr  (aerobic efficiency, cycling)
    decoupling_pct  REAL,                       -- Pw:HR drift, 1st half vs 2nd half (cycling)
    calories        REAL,
    hr_zones_json   TEXT,                       -- {"z1": secs, ... "z5": secs} time-in-zone
    notes           TEXT,                       -- user-entered session context (RPE, conditions, etc.)
    imported_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS records (
    session_id      INTEGER NOT NULL,
    t_offset_s      REAL,                       -- seconds from session start
    hr              REAL,
    power           REAL,
    cadence         REAL,
    speed           REAL,
    lat             REAL,
    lon             REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_records_session ON records(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_sport ON sessions(sport);
CREATE INDEX IF NOT EXISTS idx_sessions_race  ON sessions(is_race);
