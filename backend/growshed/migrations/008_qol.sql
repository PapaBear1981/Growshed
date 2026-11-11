-- When each switched device turned on or off (for chart timelines and energy estimates).
CREATE TABLE state_change (
    series_id INTEGER NOT NULL REFERENCES series(id),
    ts        INTEGER NOT NULL,
    value     INTEGER NOT NULL,        -- 1 = on, 0 = off
    PRIMARY KEY (series_id, ts)
) WITHOUT ROWID;

-- Recurring maintenance jobs.
CREATE TABLE reminder (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    every_days   INTEGER NOT NULL,
    last_done_at INTEGER NOT NULL
);
INSERT INTO reminder (name, every_days, last_done_at) VALUES
    ('Change the reservoir water', 14, strftime('%s','now')),
    ('Check pH and EC with a handheld meter', 7, strftime('%s','now')),
    ('Clean the exhaust filters', 30, strftime('%s','now')),
    ('Wipe the pH probe and check its storage cap', 30, strftime('%s','now')),
    ('Test the leak sensors with a wet finger', 30, strftime('%s','now'));

-- Chemical bottles on the dosing pumps: what is left is capacity minus what was dosed.
CREATE TABLE bottle (
    pump        TEXT PRIMARY KEY,      -- ph_down | ph_up | nutrient_a | nutrient_b
    capacity_ml REAL NOT NULL,
    filled_at   INTEGER NOT NULL
);

-- One row per grow, kept forever so past grows can be compared.
CREATE TABLE grow (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    zone       TEXT NOT NULL,          -- the tent (zone id) it ran in
    crop       TEXT NOT NULL DEFAULT '',
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,                -- NULL = still running
    notes      TEXT NOT NULL DEFAULT '',
    yield_g    REAL,                   -- harvest weight, if weighed
    summary    TEXT                    -- JSON snapshot of the statistics, frozen when it ends
);
ALTER TABLE plant ADD COLUMN grow_id INTEGER REFERENCES grow(id);
