"""Limits and targets that can be changed from the GUI instead of editing config.yaml.

config.yaml supplies the defaults; a change made in the GUI is stored in the database
and wins. Every value is range-checked here, and nothing in this module can reach the
safety limits that live on the nodes (interlock temperatures, dose caps): those are not
tunables at all.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import db
from .config import SiteConfig

RANGES = {  # kind -> (min, max) in SI / stored units
    "temperature": (0.0, 40.0),
    "humidity": (20.0, 95.0),
    "soil_moisture": (5.0, 80.0),
    "ph": (4.0, 8.0),
    "ec": (200.0, 3000.0),
    "ml": (0.2, 2.0),
    "watts": (0.0, 3000.0),
    "money": (0.0, 2.0),
}
MIN_PH_GAP = 0.4


@dataclass(frozen=True)
class Tunable:
    key: str
    label: str
    group: str  # a zone id, or "electricity"
    kind: str
    default: float
    low: float
    high: float


class Tunables:
    def __init__(self, conn: sqlite3.Connection, site: SiteConfig) -> None:
        self.conn = conn
        self.site = site
        self.defs: dict[str, Tunable] = {}
        self._define()

    def _add(self, key: str, label: str, group: str, kind: str, default: float, high=None) -> None:
        low, top = RANGES[kind]
        self.defs[key] = Tunable(key, label, group, kind, float(default), low, high or top)

    def _define(self) -> None:
        zones = {z.id: z for z in self.site.zones}
        # One limit per alert rule per zone, so each tent can suit its own crop.
        for rule in self.site.alerts.rules:
            if rule.when_on is not None or rule.sensor_kind not in RANGES:
                continue
            limit = rule.above if rule.above is not None else rule.below
            word = "above" if rule.above is not None else "below"
            for zone_id in sorted({s.zone for s in self.site.sensors if self._applies(rule, s)}):
                if rule.zone_kinds is None or zones[zone_id].kind in rule.zone_kinds:
                    key = alert_key(rule.name, zone_id)
                    self._add(key, f"{rule.name}: alert {word}", zone_id, rule.sensor_kind, limit)
        d = self.site.dosing
        if d is not None:
            self._add("dosing.ph_low", "Dose pH up below", d.zone, "ph", d.ph_low)
            self._add("dosing.ph_high", "Dose pH down above", d.zone, "ph", d.ph_high)
            self._add("dosing.ec_low", "Add nutrients below", d.zone, "ec", d.ec_low)
            cap = d.max_dose_ml  # never above the hub's cap, which is never above the node's
            self._add("dosing.ph_dose_ml", "pH dose size", d.zone, "ml", d.ph_dose_ml, cap)
            self._add("dosing.nutrient_dose_ml", "Nutrient dose size (each of A and B)", d.zone,
                      "ml", d.nutrient_dose_ml, cap)  # fmt: skip
        sensor_zone = {s.state_key: s.zone for s in self.site.sensors}
        for pot in self.site.watering.pots:
            self._add(f"watering.below@{pot.sensor}", f"{pot.name}: water below",
                      sensor_zone[pot.sensor], "soil_moisture", pot.below)  # fmt: skip
        self._add("price_per_kwh", "Electricity price per kWh", "electricity", "money", 0.15)
        for device in self.site.devices:
            self._add(f"watts@{device.state_key}", f"{zones[device.zone].name} · {device.name}",
                      "electricity", "watts", device.watts or 0)  # fmt: skip

    @staticmethod
    def _applies(rule, sensor) -> bool:
        return sensor.kind == rule.sensor_kind

    # ------------------------------------------------------------ reading and writing
    def get(self, key: str) -> float:
        definition = self.defs[key]
        stored = db.get_setting(self.conn, "tune:" + key, "")
        return float(stored) if stored else definition.default

    def set(self, key: str, value: float) -> None:
        """Store a new value. Raises ValueError, with a message for the user, if not allowed."""
        definition = self.defs.get(key)
        if definition is None:
            raise ValueError("Unknown setting.")
        if not definition.low <= value <= definition.high:
            raise ValueError(
                f"{definition.label} must be between {definition.low:g} and {definition.high:g}."
            )
        if key in ("dosing.ph_low", "dosing.ph_high"):
            low = value if key == "dosing.ph_low" else self.get("dosing.ph_low")
            high = value if key == "dosing.ph_high" else self.get("dosing.ph_high")
            if high - low < MIN_PH_GAP:
                # Too narrow a band makes the pumps chase each other: pH up, then pH down.
                raise ValueError(f"Keep at least {MIN_PH_GAP} pH between the two dosing limits.")
        db.set_setting(self.conn, "tune:" + key, repr(float(value)))

    def reset(self, key: str) -> None:
        if key not in self.defs:
            raise ValueError("Unknown setting.")
        self.conn.execute("DELETE FROM setting WHERE key = ?", ("tune:" + key,))
        self.conn.commit()

    def listing(self) -> list[dict]:
        out = []
        for d in self.defs.values():
            value = self.get(d.key)
            out.append({"key": d.key, "label": d.label, "group": d.group, "kind": d.kind,
                        "value": value, "default": d.default, "min": d.low, "max": d.high,
                        "changed": value != d.default})  # fmt: skip
        return out


def alert_key(rule_name: str, zone_id: str) -> str:
    return f"alert.{rule_name}@{zone_id}"
