-- Generic calibration points, replacing the soil-only table from migration 003.
--   label  which point: dry / wet (soil), ph4 / ph6.86 / ph7 ... (pH buffers),
--          ec (EC solution), offset (temperature / humidity reference)
--   raw    the sensor's own reading when the point was captured
--   ref    the true value at that point (buffer pH, solution EC, reference thermometer)
CREATE TABLE calibration_point (
    key   TEXT NOT NULL,
    label TEXT NOT NULL,
    raw   REAL NOT NULL,
    ref   REAL NOT NULL,
    ts    INTEGER NOT NULL,
    PRIMARY KEY (key, label)
);

INSERT INTO calibration_point (key, label, raw, ref, ts)
    SELECT key, 'dry', dry, 0, updated_at FROM calibration WHERE dry IS NOT NULL;
INSERT INTO calibration_point (key, label, raw, ref, ts)
    SELECT key, 'wet', wet, 100, updated_at FROM calibration WHERE wet IS NOT NULL;

DROP TABLE calibration;
