-- Every dose the hub asked a chemical pump for (Phase 4). Used for the daily caps,
-- the waiting time between doses, and checking that a dose had the expected effect.
CREATE TABLE chem_dose (
    id        INTEGER PRIMARY KEY,
    ts        INTEGER NOT NULL,
    kind      TEXT NOT NULL,          -- ph_down | ph_up | nutrients
    pump      TEXT NOT NULL,          -- ph_down | ph_up | nutrient_a | nutrient_b
    ml        REAL NOT NULL,
    source    TEXT NOT NULL,          -- auto | approved | manual
    ph_before REAL,
    ec_before REAL,
    judged    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX chem_dose_ts ON chem_dose (ts);
