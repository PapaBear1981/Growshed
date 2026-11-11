"""Turns raw sensor values into meaningful ones, using calibrations stored in SQLite.

Soil moisture sensors report a voltage that differs from sensor to sensor, so each one
is calibrated at two points from the GUI: in open air (0 %) and in water (100 %).
History keeps the raw voltage; the percentage is computed when shown, so recalibrating
a sensor also corrects its past readings.

An uncalibrated sensor has NO value (None), never a guessed percentage: a made-up
number here would later drive watering decisions.
"""

from __future__ import annotations

import sqlite3

SOIL = "soil_moisture"
MIN_SPAN = 0.2  # volts between the dry and wet points; less means a calibration mistake


class Calibrations:
    def __init__(self, conn: sqlite3.Connection, kinds: dict[str, str]) -> None:
        self.conn = conn
        self.kinds = kinds  # sensor key -> sensor kind, from config.yaml
        self.points: dict[str, dict[str, float | None]] = {
            row["key"]: {"dry": row["dry"], "wet": row["wet"]}
            for row in conn.execute("SELECT key, dry, wet FROM calibration")
        }

    def needs_calibration(self, key: str) -> bool:
        return self.kinds.get(key) == SOIL

    def is_calibrated(self, key: str) -> bool:
        point = self.points.get(key)
        if not point or point["dry"] is None or point["wet"] is None:
            return False
        return abs(point["dry"] - point["wet"]) >= MIN_SPAN

    def apply(self, key: str, raw: float | None) -> float | None:
        """Raw reading -> calibrated value. Sensors that need no calibration pass through."""
        if not self.needs_calibration(key):
            return raw
        if raw is None or not self.is_calibrated(key):
            return None
        point = self.points[key]
        percent = (point["dry"] - raw) / (point["dry"] - point["wet"]) * 100
        # A reading slightly outside the two calibration points is normal: clamp it.
        return round(max(0.0, min(100.0, percent)), 1)

    def set_point(self, key: str, which: str, raw: float, now: float) -> None:
        if which not in ("dry", "wet"):
            raise ValueError(which)
        point = self.points.setdefault(key, {"dry": None, "wet": None})
        point[which] = raw
        self.conn.execute(
            "INSERT INTO calibration (key, dry, wet, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET dry = excluded.dry, wet = excluded.wet, "
            "updated_at = excluded.updated_at",
            (key, point["dry"], point["wet"], int(now)),
        )
        self.conn.commit()

    def summary(self) -> dict[str, dict]:
        """For the GUI: every sensor that needs calibrating, with its stored points."""
        return {
            key: {**self.points.get(key, {"dry": None, "wet": None}),
                  "calibrated": self.is_calibrated(key)}
            for key in self.kinds
            if self.needs_calibration(key)
        }  # fmt: skip
