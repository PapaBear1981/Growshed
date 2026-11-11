"""Site configuration (config.yaml) and runtime settings (environment variables).

config.yaml describes the physical garden: zones (tents, room, reservoirs), the ESP32
nodes, and which MQTT entities are sensors or switchable devices. Keeping this in one
reviewed file means adding a tent is a config change, not a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

ZoneKind = Literal["tent", "room", "rdwc", "kratky", "tower", "soil"]
DeviceKind = Literal["heater", "light", "pump", "fan", "valve", "doser"]


class Zone(BaseModel):
    id: str
    name: str
    kind: ZoneKind
    parent: str | None = None  # e.g. the tower lives inside the tower tent


class Node(BaseModel):
    id: str
    name: str


class Sensor(BaseModel):
    node: str
    key: str  # ESPHome entity id, e.g. "air_temp"
    component: Literal["sensor", "binary_sensor"] = "sensor"
    zone: str
    kind: str  # temperature, humidity, illuminance, leak, level_low, level_high
    unit: str = ""  # SI unit as published on MQTT
    name: str

    @property
    def state_key(self) -> str:
        return f"{self.node}/{self.component}/{self.key}"


class Device(BaseModel):
    node: str
    key: str  # ESPHome switch id, e.g. "lights"
    zone: str
    kind: DeviceKind
    name: str
    circuit: str | None = None  # which house breaker feeds it (for load budgeting)
    watts: float | None = None
    # "mode": auto/on/off relay. "dose": a pump that only runs briefly on request.
    # "doser": a chemical dosing pump, driven only by the dosing logic (millilitres).
    control: Literal["mode", "dose", "doser"] = "mode"
    dose_s: float = 8  # seconds requested per dose (the node enforces its own maximum)

    @property
    def state_key(self) -> str:
        return f"{self.node}/switch/{self.key}"

    @property
    def mode_key(self) -> str:
        return f"{self.node}/select/{self.key}_mode"

    @property
    def source_key(self) -> str:
        return f"{self.node}/text_sensor/{self.key}_source"


class Setting(BaseModel):
    """A value stored on a node that the hub may change (schedule times, limits, setpoints)."""

    node: str
    key: str  # ESPHome number id, e.g. "light_on_minute"
    zone: str
    kind: Literal["time_of_day", "temperature", "humidity", "duration"]
    name: str
    min: float
    max: float

    @property
    def state_key(self) -> str:
        return f"{self.node}/number/{self.key}"


class WateringPot(BaseModel):
    """Pairs a soil sensor with the pump that waters that pot (docs/SAFETY.md §4b)."""

    name: str
    sensor: str  # sensor key, e.g. tent2/sensor/soil_1
    pump: str  # device key, e.g. tent2/switch/water_1
    tank_low: str  # binary sensor key of the watering tank's low float
    below: float = 35  # water when moisture drops below this many percent


class WateringConfig(BaseModel):
    pots: list[WateringPot] = []
    soak_s: float = 1800  # wait after a dose before judging the result or dosing again
    max_doses_per_day: int = 6
    min_rise: float = 2.0  # percentage points the reading must rise after a dose
    max_strikes: int = 2  # doses in a row without that rise before auto-watering stops


class AlertRule(BaseModel):
    """Applies to every sensor of `sensor_kind` (optionally only in some kinds of zone).

    Matching by kind instead of naming sensors means a newly added tent is covered
    by the same rules automatically.
    """

    name: str
    sensor_kind: str
    zone_kinds: list[ZoneKind] | None = None
    above: float | None = None  # numeric sensors, SI units
    below: float | None = None
    when_on: bool | None = None  # binary sensors: alert while ON (true) or OFF (false)
    for_s: float = 0  # the condition must hold this long before alerting
    severity: Literal["warning", "critical"] = "warning"
    repeat_s: float | None = None  # re-notify this often until acknowledged

    @model_validator(mode="after")
    def _one_condition(self) -> AlertRule:
        given = [v for v in (self.above, self.below, self.when_on) if v is not None]
        if len(given) != 1:
            raise ValueError(f"alert rule {self.name!r}: set exactly one of above/below/when_on")
        return self


class AlertConfig(BaseModel):
    rules: list[AlertRule] = []
    node_offline_after_s: float = 300
    sensor_stale_after_s: float = 600
    clear_after_s: float = 60  # a condition must stay good this long before the alert clears


class DosingConfig(BaseModel):
    """Automatic pH and nutrient dosing for one reservoir (docs/SAFETY.md §4)."""

    zone: str
    ph_sensor: str
    ec_sensor: str
    circulation: str  # device key of the pump that mixes the reservoir
    level_low: str  # sensor key of the reservoir's low float
    ph_down: str  # device keys of the four pumps
    ph_up: str
    nutrient_a: str
    nutrient_b: str
    ph_low: float = 5.6  # dose pH up below this
    ph_high: float = 6.2  # dose pH down above this
    ec_low: float = 1000  # µS/cm: add nutrients below this. Nothing is ever diluted.
    ph_dose_ml: float = 1.0
    nutrient_dose_ml: float = 2.0  # of EACH of A and B
    max_dose_ml: float = 2.0  # must not exceed the node's own limit (firmware/dosing.yaml)
    max_day_ml: float = 20.0
    wait_s: float = 900  # mixing time after any dose before measuring or dosing again

    @model_validator(mode="after")
    def _sane(self) -> DosingConfig:
        if not self.ph_low < self.ph_high:
            raise ValueError("dosing: ph_low must be below ph_high")
        if self.ph_high - self.ph_low < 0.4:
            raise ValueError("dosing: leave at least 0.4 pH between ph_low and ph_high")
        if max(self.ph_dose_ml, self.nutrient_dose_ml) > self.max_dose_ml:
            raise ValueError("dosing: a dose is larger than max_dose_ml")
        if self.max_dose_ml > 2.0 or self.max_day_ml > 20.0:
            raise ValueError("dosing: limits are above the node's hard limits (2 mL, 20 mL/day)")
        if self.wait_s < 900:
            raise ValueError("dosing: wait_s must be at least 900 (15 minutes)")
        return self

    @property
    def pumps(self) -> dict[str, str]:
        return {
            "ph_down": self.ph_down, "ph_up": self.ph_up,
            "nutrient_a": self.nutrient_a, "nutrient_b": self.nutrient_b,
        }  # fmt: skip


class SiteConfig(BaseModel):
    zones: list[Zone]
    nodes: list[Node]
    sensors: list[Sensor] = []
    devices: list[Device] = []
    settings: list[Setting] = []
    watering: WateringConfig = WateringConfig()
    dosing: DosingConfig | None = None
    alerts: AlertConfig = AlertConfig()

    @model_validator(mode="after")
    def _check_references(self) -> SiteConfig:
        zone_ids = [z.id for z in self.zones]
        node_ids = [n.id for n in self.nodes]
        for label, ids in (("zone", zone_ids), ("node", node_ids)):
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                raise ValueError(f"duplicate {label} id(s): {sorted(dupes)}")
        for zone in self.zones:
            if zone.parent is not None and zone.parent not in zone_ids:
                raise ValueError(f"zone {zone.id!r}: unknown parent {zone.parent!r}")
        names = [r.name for r in self.alerts.rules]
        if len(names) != len(set(names)):
            raise ValueError("alert rule names must be unique")
        seen: set[str] = set()
        for item in [*self.sensors, *self.devices, *self.settings]:
            if item.zone not in zone_ids:
                raise ValueError(f"{item.state_key}: unknown zone {item.zone!r}")
            if item.node not in node_ids:
                raise ValueError(f"{item.state_key}: unknown node {item.node!r}")
            if item.state_key in seen:
                raise ValueError(f"duplicate entity {item.state_key}")
            seen.add(item.state_key)
        for setting in self.settings:
            if setting.min >= setting.max:
                raise ValueError(f"{setting.state_key}: min must be below max")
        sensors = {s.state_key: s for s in self.sensors}
        devices = {d.state_key: d for d in self.devices}
        if self.dosing is not None:
            d = self.dosing
            for key in (d.ph_sensor, d.ec_sensor, d.level_low):
                if key not in sensors:
                    raise ValueError(f"dosing: unknown sensor {key!r}")
            if d.circulation not in devices:
                raise ValueError(f"dosing: unknown device {d.circulation!r}")
            for name, key in d.pumps.items():
                if devices.get(key) is None or devices[key].control != "doser":
                    raise ValueError(f"dosing: {name} pump {key!r} is not a 'doser' device")
        for pot in self.watering.pots:
            if sensors.get(pot.sensor) is None or sensors[pot.sensor].kind != "soil_moisture":
                raise ValueError(f"watering pot {pot.name!r}: {pot.sensor!r} is not a soil sensor")
            if devices.get(pot.pump) is None or devices[pot.pump].control != "dose":
                raise ValueError(f"watering pot {pot.name!r}: {pot.pump!r} is not a dose pump")
            if pot.tank_low not in sensors:
                raise ValueError(f"watering pot {pot.name!r}: unknown tank sensor {pot.tank_low!r}")
        return self


def load_config(path: str | Path) -> SiteConfig:
    with open(path, encoding="utf-8") as fh:
        return SiteConfig.model_validate(yaml.safe_load(fh))


_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    """Runtime settings. Every field can be overridden with a GROWSHED_* env var."""

    config_path: Path = _REPO_ROOT / "config" / "config.yaml"
    db_path: Path = _REPO_ROOT / "data" / "growshed.db"
    static_dir: Path = _REPO_ROOT / "frontend" / "dist"
    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    heartbeat_interval_s: float = 30.0
    background_enabled: bool = True  # recorder, alert engine, clean-up (off in unit tests)
    ntfy_url: str | None = None  # full topic URL, e.g. https://ntfy.sh/growshed-3f9a...
    ntfy_token: str | None = None
    healthcheck_url: str | None = None  # dead man's switch: pinged every 5 minutes

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        s = cls()
        s.config_path = Path(env.get("GROWSHED_CONFIG_PATH", s.config_path))
        s.db_path = Path(env.get("GROWSHED_DB_PATH", s.db_path))
        s.static_dir = Path(env.get("GROWSHED_STATIC_DIR", s.static_dir))
        s.mqtt_enabled = env.get("GROWSHED_MQTT_ENABLED", "1") not in ("0", "false", "no")
        s.mqtt_host = env.get("GROWSHED_MQTT_HOST", s.mqtt_host)
        s.mqtt_port = int(env.get("GROWSHED_MQTT_PORT", s.mqtt_port))
        s.mqtt_user = env.get("GROWSHED_MQTT_USER") or None
        s.mqtt_password = env.get("GROWSHED_MQTT_PASSWORD") or None
        s.ntfy_url = env.get("GROWSHED_NTFY_URL") or None
        s.ntfy_token = env.get("GROWSHED_NTFY_TOKEN") or None
        s.healthcheck_url = env.get("GROWSHED_HEALTHCHECK_URL") or None
        return s
