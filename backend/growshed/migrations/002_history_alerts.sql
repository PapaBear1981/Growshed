-- One row per stored measurement stream, so readings can use a small integer id.
CREATE TABLE series (
    id  INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE          -- "node/component/entity", e.g. tent1/sensor/air_temp
);

-- Raw readings (SI units, UTC epoch seconds). Kept 30 days.
CREATE TABLE reading (
    series_id INTEGER NOT NULL REFERENCES series(id),
    ts        INTEGER NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (series_id, ts)
) WITHOUT ROWID;

-- 5-minute summaries, kept 1 year. ts is the start of the bucket.
CREATE TABLE reading_5m (
    series_id INTEGER NOT NULL REFERENCES series(id),
    ts        INTEGER NOT NULL,
    min       REAL NOT NULL,
    max       REAL NOT NULL,
    avg       REAL NOT NULL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (series_id, ts)
) WITHOUT ROWID;

-- Hourly summaries, kept forever.
CREATE TABLE reading_1h (
    series_id INTEGER NOT NULL REFERENCES series(id),
    ts        INTEGER NOT NULL,
    min       REAL NOT NULL,
    max       REAL NOT NULL,
    avg       REAL NOT NULL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (series_id, ts)
) WITHOUT ROWID;

-- Every time an alert condition became active. ended_at NULL = still active.
CREATE TABLE alert_event (
    id         INTEGER PRIMARY KEY,
    key        TEXT NOT NULL,         -- stable id of the condition, e.g. "rule:Leak detected:tent1/binary_sensor/leak"
    name       TEXT NOT NULL,
    subject    TEXT NOT NULL,
    severity   TEXT NOT NULL,         -- warning | critical
    detail     TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    acked_at   INTEGER
);
CREATE INDEX alert_event_open ON alert_event (ended_at);
CREATE INDEX alert_event_started ON alert_event (started_at);
