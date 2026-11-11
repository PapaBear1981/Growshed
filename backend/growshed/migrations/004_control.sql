-- Manual device modes that should revert to "auto" by themselves.
CREATE TABLE device_override (
    key        TEXT PRIMARY KEY,      -- device key, e.g. tent1/switch/lights
    mode       TEXT NOT NULL,         -- on | off
    expires_at INTEGER NOT NULL
);

-- Every dose the hub asked a pump for (soil watering, top-off).
CREATE TABLE dose_event (
    id         INTEGER PRIMARY KEY,
    ts         INTEGER NOT NULL,
    device_key TEXT NOT NULL,
    seconds    REAL NOT NULL,
    source     TEXT NOT NULL,         -- manual | auto
    pre_value  REAL                   -- soil moisture % just before, when known
);
CREATE INDEX dose_event_device ON dose_event (device_key, ts);

-- Per-pot automatic watering state. Defaults to OFF: a human turns AUTO on.
CREATE TABLE watering_pot (
    sensor_key TEXT PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT 'off',   -- off | auto
    strikes    INTEGER NOT NULL DEFAULT 0,    -- doses in a row with no moisture rise
    locked     TEXT,                          -- why auto-watering was stopped, or NULL
    judged_ts  INTEGER NOT NULL DEFAULT 0     -- ts of the last dose whose result was checked
);
