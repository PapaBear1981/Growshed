"""Sensor calibration: turns each sensor's own reading into a trustworthy value.

Built for cheap hobby sensors, which are usable but need help:

- Soil moisture, pH and EC probes report a raw voltage that differs from probe to probe
  and drifts with age. They have NO value until calibrated: a guessed number here would
  later drive watering or dosing decisions.
- Temperature and humidity sensors work out of the box but can be a degree or a few
  percent off. They take an optional offset against a reference.

What is automatic:
- Capture waits until the reading is steady (several samples that agree) and stores their
  average, so a point is never taken from a probe that is still settling.
- EC is corrected to 25 °C using the reservoir's own temperature probe.
- Calibrations age: pH and EC raise a reminder when they are due again.

History keeps the raw reading; calibration is applied when values are shown, so
recalibrating a sensor also corrects its past readings.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from collections.abc import Callable

SOIL = "soil_moisture"
PH = "ph"
EC = "ec"
REQUIRED = {SOIL, PH, EC}  # no value until calibrated
MAX_OFFSET = {"temperature": 5.0, "humidity": 15.0}  # optional; larger means a faulty sensor

# How closely recent readings must agree before a point is captured (in the raw unit).
TOLERANCE = {SOIL: 0.03, PH: 0.012, EC: 0.03, "temperature": 0.3, "humidity": 2.0}
WINDOW_S = 100
MIN_SAMPLES = 3

# Cheap probes drift: remind the owner to recalibrate.
MAX_AGE_DAYS = {PH: 30, EC: 90}

MIN_SOIL_SPAN = 0.2  # volts between dry and wet; less means a calibration mistake
MIN_PH_SPAN = 0.1  # volts between the outermost buffers
PH_BUFFERS = (4.0, 4.01, 6.86, 7.0, 9.18, 10.0, 10.01)


def ec_from_volts(volts: float) -> float:
    """Uncalibrated EC in µS/cm from a "TDS meter" board's output voltage.

    This is the published curve for the common analog TDS board (its ppm figure is half
    of this). Every board and probe differs, so the result is only a starting shape: the
    one-point calibration against a known solution scales it.
    """
    return 133.42 * volts**3 - 255.86 * volts**2 + 857.39 * volts


def compensate_ec_volts(volts: float, water_temp_c: float) -> float:
    """Conductivity rises about 2 % per °C. Refer the reading to 25 °C."""
    return volts / (1 + 0.02 * (water_temp_c - 25.0))


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Least-squares line through (raw, ref) points: (intercept, slope, worst residual)."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sxx
    intercept = mean_y - slope * mean_x
    residual = max(abs(intercept + slope * x - y) for x, y in points)
    return intercept, slope, residual


class Calibrations:
    def __init__(
        self,
        conn: sqlite3.Connection,
        kinds: dict[str, str],
        water_temp: Callable[[str], float | None] = lambda key: None,
    ) -> None:
        self.conn = conn
        self.kinds = kinds  # sensor key -> sensor kind, from config.yaml
        self.water_temp = water_temp  # EC sensor key -> its reservoir's temperature (°C)
        self.points: dict[str, dict[str, dict]] = {}
        for row in conn.execute("SELECT key, label, raw, ref, ts FROM calibration_point"):
            self.points.setdefault(row["key"], {})[row["label"]] = {
                "raw": row["raw"], "ref": row["ref"], "ts": row["ts"],
            }  # fmt: skip
        self.recent: dict[str, deque[tuple[float, float]]] = {}

    # ------------------------------------------------------------ what applies to a sensor
    def uses(self, key: str) -> bool:
        kind = self.kinds.get(key)
        return kind in REQUIRED or kind in MAX_OFFSET

    def required(self, key: str) -> bool:
        return self.kinds.get(key) in REQUIRED

    def prepare(self, key: str, raw: float | None) -> float | None:
        """Pre-process a raw reading before it is stored or calibrated.

        EC volts are referred to 25 °C here, so history and calibration never need to
        know what the water temperature was at the time. With no water temperature
        there is no trustworthy EC, so there is no value.
        """
        if raw is None or self.kinds.get(key) != EC:
            return raw
        temp = self.water_temp(key)
        return None if temp is None else compensate_ec_volts(raw, temp)

    def observe(self, key: str, raw: float, ts: float) -> None:
        """Remember recent readings so capture can tell whether the sensor has settled."""
        self.recent.setdefault(key, deque(maxlen=40)).append((ts, raw))

    # ------------------------------------------------------------ applying
    def _ph_line(self, key: str) -> tuple[float, float, float] | None:
        pts = [(p["raw"], p["ref"]) for p in self.points.get(key, {}).values()]
        if len(pts) < 2 or max(x for x, _ in pts) - min(x for x, _ in pts) < MIN_PH_SPAN:
            return None
        if max(y for _, y in pts) - min(y for _, y in pts) < 2.0:
            return None
        return fit_line(pts)

    def is_calibrated(self, key: str) -> bool:
        kind, pts = self.kinds.get(key), self.points.get(key, {})
        if kind == SOIL:
            if "dry" not in pts or "wet" not in pts:
                return False
            return abs(pts["dry"]["raw"] - pts["wet"]["raw"]) >= MIN_SOIL_SPAN
        if kind == PH:
            return self._ph_line(key) is not None
        if kind == EC:
            return "ec" in pts and ec_from_volts(pts["ec"]["raw"]) > 50
        return "offset" in pts

    def raw_percent(self, key: str, raw: float | None) -> float | None:
        """Soil moisture NOT clamped, so a reading far outside the calibrated range
        (a sensor that fell out of its pot, a broken wire) can be recognised."""
        if raw is None or self.kinds.get(key) != SOIL or not self.is_calibrated(key):
            return None
        dry, wet = self.points[key]["dry"]["raw"], self.points[key]["wet"]["raw"]
        return (dry - raw) / (dry - wet) * 100

    def apply(self, key: str, raw: float | None) -> float | None:
        """Prepared raw reading -> value. Sensors without calibration pass through."""
        kind = self.kinds.get(key)
        if raw is None or not self.uses(key):
            return raw
        if kind in MAX_OFFSET:
            point = self.points.get(key, {}).get("offset")
            return raw if point is None else round(raw + point["ref"] - point["raw"], 2)
        if not self.is_calibrated(key):
            return None
        if kind == SOIL:
            # A reading slightly outside the two calibration points is normal: clamp it.
            return round(max(0.0, min(100.0, self.raw_percent(key, raw))), 1)
        if kind == PH:
            intercept, slope, _ = self._ph_line(key)
            return round(max(0.0, min(14.0, intercept + slope * raw)), 2)
        point = self.points[key]["ec"]
        factor = point["ref"] / ec_from_volts(point["raw"])
        return round(max(0.0, factor * ec_from_volts(raw)))

    # ------------------------------------------------------------ changing
    def set_point(self, key: str, label: str, raw: float, now: float, ref: float | None = None):
        """Store one calibration point. Raises ValueError for an impossible request."""
        kind = self.kinds.get(key)
        pts = self.points.setdefault(key, {})
        if kind == SOIL:
            if label not in ("dry", "wet"):
                raise ValueError("Soil sensors have a 'dry' and a 'wet' point.")
            ref = 0.0 if label == "dry" else 100.0
        elif kind == PH:
            if ref is None or not 1 <= ref <= 13:
                raise ValueError("Say which buffer the probe is in (its pH value).")
            # A new point replaces an older one for (nearly) the same buffer.
            for old in [name for name, p in pts.items() if abs(p["ref"] - ref) < 1.0]:
                self._delete(key, old)
            label = f"ph{ref:g}"
        elif kind == EC:
            if ref is None or not 100 <= ref <= 5000:
                raise ValueError("Enter the calibration solution's EC in µS/cm (for example 1413).")
            if ec_from_volts(raw) <= 50:
                raise ValueError("The probe reads almost nothing. Is it in the solution?")
            label = "ec"
        elif kind in MAX_OFFSET:
            if ref is None:
                raise ValueError("Enter the reference value.")
            if abs(ref - raw) > MAX_OFFSET[kind]:
                raise ValueError(
                    f"That is {abs(ref - raw):.1f} away from what the sensor reads. "
                    "A sensor this far off is faulty or badly placed: fix that instead."
                )
            label = "offset"
        else:
            raise ValueError("That sensor does not use calibration.")
        pts[label] = {"raw": raw, "ref": ref, "ts": int(now)}
        self.conn.execute(
            "INSERT OR REPLACE INTO calibration_point (key, label, raw, ref, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, label, raw, ref, int(now)),
        )
        self.conn.commit()

    def _delete(self, key: str, label: str) -> None:
        self.points.get(key, {}).pop(label, None)
        self.conn.execute("DELETE FROM calibration_point WHERE key = ? AND label = ?", (key, label))

    def clear(self, key: str) -> None:
        self.points.pop(key, None)
        self.conn.execute("DELETE FROM calibration_point WHERE key = ?", (key,))
        self.conn.commit()

    def capture(self, key: str, label: str, ref: float | None, now: float) -> dict:
        """Take a calibration point from the sensor's recent readings, once they agree.

        Returns {"status": "saved"} or {"status": "waiting", "reason": ...}. The GUI
        simply asks again every few seconds until it is saved.
        """
        kind = self.kinds.get(key)
        # Judge only the newest few readings: after a probe is moved to another solution,
        # the older ones describe the previous solution and must not hold things up.
        samples = [raw for ts, raw in self.recent.get(key, ()) if now - ts <= WINDOW_S]
        samples = samples[-MIN_SAMPLES:]
        if len(samples) < MIN_SAMPLES:
            return {
                "status": "waiting",
                "reason": "waiting for readings from the sensor",
                "samples": len(samples),
            }
        spread = max(samples) - min(samples)
        if spread > TOLERANCE.get(kind, 0):
            return {
                "status": "waiting",
                "reason": "the reading is still settling",
                "samples": len(samples),
                "spread": round(spread, 4),
            }
        self.set_point(key, label, sum(samples) / len(samples), now, ref)
        return {"status": "saved"}

    # ------------------------------------------------------------ reporting
    def age_days(self, key: str, now: float) -> float | None:
        """Days since the OLDEST point of a calibrated sensor was taken."""
        pts = self.points.get(key, {})
        if not pts or not self.is_calibrated(key):
            return None
        return (now - min(p["ts"] for p in pts.values())) / 86400

    def warning(self, key: str) -> str | None:
        """Something about the stored calibration the owner should know."""
        kind, pts = self.kinds.get(key), self.points.get(key, {})
        if kind == SOIL and len(pts) == 2 and not self.is_calibrated(key):
            return "Dry and wet points are almost the same. Redo both."
        if kind == PH and len(pts) >= 2:
            line = self._ph_line(key)
            if line is None:
                return "The buffer readings are almost the same. Rinse the probe and redo them."
            if line[2] > 0.2:
                return "The points do not fall on a line. The probe may be worn out or dirty."
        return None

    def summary(self) -> dict[str, dict]:
        """For the GUI: every sensor that can be calibrated, with its stored points."""
        return {
            key: {
                "kind": kind,
                "required": kind in REQUIRED,
                "points": self.points.get(key, {}),
                "calibrated": self.is_calibrated(key),
                "warning": self.warning(key),
                "max_age_days": MAX_AGE_DAYS.get(kind),
            }
            for key, kind in self.kinds.items()
            if self.uses(key)
        }
