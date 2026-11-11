-- Two-point calibration for sensors that report a raw value (soil moisture: volts).
-- dry = reading in open air (0 %), wet = reading in a glass of water (100 %).
CREATE TABLE calibration (
    key        TEXT PRIMARY KEY,      -- "node/component/entity"
    dry        REAL,
    wet        REAL,
    updated_at INTEGER NOT NULL
);
