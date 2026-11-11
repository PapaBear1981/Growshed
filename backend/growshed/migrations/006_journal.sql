-- What was added to a reservoir by hand (Phase 3: manual dosing).
CREATE TABLE dose_log (
    id      INTEGER PRIMARY KEY,
    ts      INTEGER NOT NULL,
    zone    TEXT NOT NULL,            -- which reservoir, e.g. rdwc
    product TEXT NOT NULL,            -- "pH down", "Nutrient A", ...
    amount  REAL NOT NULL,
    unit    TEXT NOT NULL,            -- mL | L | g
    note    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX dose_log_zone ON dose_log (zone, ts);

CREATE TABLE plant (
    id         INTEGER PRIMARY KEY,
    zone       TEXT NOT NULL,         -- where it grows (a zone id from config.yaml)
    name       TEXT NOT NULL,
    variety    TEXT NOT NULL DEFAULT '',
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,               -- harvested / removed; NULL = still growing
    notes      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE journal_entry (
    id       INTEGER PRIMARY KEY,
    ts       INTEGER NOT NULL,
    plant_id INTEGER REFERENCES plant(id) ON DELETE CASCADE,   -- NULL = a general note
    text     TEXT NOT NULL DEFAULT '',
    photo    TEXT                     -- file name under data/photos, or NULL
);
CREATE INDEX journal_entry_ts ON journal_entry (ts);
