"""Pure simulation models (no MQTT, no clocks) so behaviour is unit-testable.

Each model mirrors what the real ESPHome node does (firmware/common/*_control.yaml):
the same modes, settings, interlocks and dosing limits, published under the same entity
names. The physics is only meant to look plausible on the dashboard.
"""

from __future__ import annotations

import math
import random

from . import control as c

Entity = tuple[str, str, str]  # (component, entity id, payload)


def approach(current: float, target: float, dt_s: float, tau_s: float) -> float:
    """Move `current` toward `target` with time constant `tau_s` (first-order lag)."""
    return target + (current - target) * math.exp(-dt_s / tau_s)


def on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def first(*rules: tuple[object, str]) -> str | None:
    """The id of the first rule whose condition is true: first((leak, "I-10"), (low, "I-8"))."""
    return next((rule for condition, rule in rules if condition), None)


def tds_volts(ec_us: float) -> float:
    """Voltage a cheap TDS board gives for a conductivity (at 25 °C): the inverse of the
    curve the hub uses, found by bisection."""
    low, high = 0.0, 3.0
    for _ in range(40):
        mid = (low + high) / 2
        if 133.42 * mid**3 - 255.86 * mid**2 + 857.39 * mid < ec_us:
            low = mid
        else:
            high = mid
    return low


def room_conditions(hour: float) -> tuple[float, float]:
    """Basement air (°C, %RH): steady, with a small daily swing."""
    phase = 2 * math.pi * (hour - 9) / 24
    return 18.0 + 1.0 * math.sin(phase), 50.0 - 4.0 * math.sin(phase)


class NodeModel:
    """Shared behaviour: device modes, settings, dose requests, faults, published entities."""

    devices: tuple[str, ...] = ()  # mode-controlled relays
    limits: dict[str, tuple[float, float]] = {}  # setting -> (min, max), as in the firmware

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.dosers: dict[str, c.Doser] = {}  # dose-only pumps
        self.modes: dict[str, str] = dict.fromkeys(self.devices, "auto")
        self.numbers: dict[str, float] = {}
        self.state: dict[str, bool] = dict.fromkeys(self.devices, False)
        self.source: dict[str, str] = dict.fromkeys(self.devices, "auto")
        self.requests: dict[str, float] = {}
        self._reported: dict[str, str] = {}
        self.last_interlock = ""
        self.fallback = False  # set by the runner when the hub heartbeat is missing
        self.hub_leak = False  # growshed/hub/leak_alarm
        self.sensor_fail = False

    def add_doser(self, name: str, doser: c.Doser) -> None:
        self.dosers[name] = doser
        self.state[name] = False
        self.source[name] = "idle"

    # ---- commands from the hub
    def set_mode(self, device: str, mode: str) -> bool:
        if device not in self.modes or mode not in c.MODES:
            return False
        self.modes[device] = mode
        return True

    def set_number(self, name: str, value: float) -> bool:
        if name not in self.numbers or math.isnan(value):
            return False
        low, high = self.limits[name]
        self.numbers[name] = max(low, min(high, value))  # the node clamps, like ESPHome
        return True

    def request_dose(self, device: str, seconds: float) -> bool:
        if device not in self.dosers:
            return False
        self.requests[device] = seconds
        return True

    # ---- helpers for subclasses
    def _drive(self, device: str, auto_on: bool, block: str | None, force: str | None) -> bool:
        d = c.decide(self.modes[device], self.fallback, auto_on, block, force)
        self._report(device, d.on, d.source, d.interlock)
        return d.on

    def _dose(self, device: str, block: str | None, dt_s: float) -> float:
        doser = self.dosers[device]
        ran = doser.step(self.requests.pop(device, 0), block, dt_s)
        on = ran > 0
        self._report(device, on, doser.status(on), None if on else doser.refused)
        return ran

    def _report(self, device: str, on: bool, source: str, interlock: str | None) -> None:
        # Like gs::report in control.h: publish the interlock whenever source or rule changes.
        signature = f"{source} {interlock}"
        if interlock and self._reported.get(device) != signature:
            self.last_interlock = f"{interlock} {device}"
        self._reported[device] = signature
        self.state[device] = on
        self.source[device] = source

    def _noisy(self, value: float, sigma: float, digits: int) -> str:
        if self.sensor_fail:
            return "nan"  # what ESPHome publishes when a read fails
        return f"{value + self.rng.gauss(0, sigma):.{digits}f}"

    def fault(self, text: str) -> bool:
        """Handle a fault command such as "leak on". Returns False if not understood."""
        if text in ("sensor_fail on", "sensor_fail off"):
            self.sensor_fail = text.endswith("on")
            return True
        return False

    def control_entities(self) -> list[Entity]:
        out: list[Entity] = []
        for name, on in self.state.items():
            out.append(("switch", name, on_off(on)))
            out.append(("text_sensor", f"{name}_source", self.source[name]))
        out += [("select", f"{name}_mode", mode) for name, mode in self.modes.items()]
        out += [("number", name, f"{value:g}") for name, value in self.numbers.items()]
        out.append(("text_sensor", "last_interlock", self.last_interlock))
        return out


class TentModel(NodeModel):
    """A grow tent: lights heat it, plants humidify it, the exhaust fan fixes both."""

    # Capacitive soil sensors: about this many volts in air (dry) and in water (wet).
    SOIL_DRY_V = 2.6
    SOIL_WET_V = 1.2
    limits = {
        "light_on_minute": (0, 1439),
        "light_off_minute": (0, 1439),
        "max_temp": (20, 30),
        "max_rh": (40, 90),
        "tower_on_s": (0, 3600),
        "tower_off_s": (0, 14400),
    }

    def __init__(self, seed: int = 0, has_tower: bool = False, soil_pots: int = 0) -> None:
        self.has_tower = has_tower
        self.devices = ("lights", "exhaust_fan") + (("tower_pump",) if has_tower else ())
        super().__init__(seed)
        self.numbers = {"light_on_minute": 360, "light_off_minute": 1320}
        self.numbers.update(max_temp=28, max_rh=70)
        if has_tower:
            self.numbers.update(tower_on_s=900, tower_off_s=2700)
        self.soil = [0.55, 0.45, 0.65, 0.50, 0.60, 0.40][:soil_pots]  # 0 = bone dry, 1 = soaked
        self.soil_unplugged: set[int] = set()  # pots whose sensor fell out: reads "dry" forever
        for n in range(1, soil_pots + 1):
            self.add_doser(f"water_{n}", c.Doser(20, 600, 8))
        self.air_temp = 21.0
        self.air_rh = 60.0
        self.tower_temp = 19.0
        self.leak = False
        self.tower_low = False
        self.tank_low = False
        self._fan_auto = False
        self._too_hot = c.OverTemp()
        self._sensor_dead = c.Held()
        self._seconds = 0.0

    def fault(self, text: str) -> bool:
        if text in ("leak on", "leak off"):
            self.leak = text.endswith("on")
            return True
        if self.soil and text in ("soil_dry", "soil_water"):
            self.soil = [0.1 if text == "soil_dry" else 0.8] * len(self.soil)
            return True
        if self.soil and text in ("soil_unplug", "soil_replug"):
            self.soil_unplugged = {0} if text == "soil_unplug" else set()
            return True
        if self.soil and text in ("tank_low on", "tank_low off"):
            self.tank_low = text.endswith("on")
            return True
        if self.has_tower and text in ("tower_low on", "tower_low off"):
            self.tower_low = text.endswith("on")
            return True
        return super().fault(text)

    def step(self, dt_s: float, hour: float) -> None:
        room_temp, room_rh = room_conditions(hour)
        temp = math.nan if self.sensor_fail else self.air_temp
        rh = math.nan if self.sensor_fail else self.air_rh
        leak = self.leak or self.hub_leak
        n = self.numbers

        # Lights: daily window; I-4 over-temperature cutoff.
        window = int(n["light_on_minute"]), int(n["light_off_minute"])
        lights_auto = c.in_window(int(hour * 60), *window)
        tripped = self._too_hot.update(temp, 35.0, 30.0, dt_s, 120)
        lights = self._drive("lights", lights_auto, "I-4" if tripped else None, None)

        # Exhaust: limits with hysteresis; I-5 forced on when hot or the sensor is dead.
        self._fan_auto = c.exhaust_demand(self._fan_auto, temp, rh, n["max_temp"], n["max_rh"])
        dead = self._sensor_dead.update(math.isnan(temp), dt_s, 120)
        hot = not math.isnan(temp) and temp > 30.0
        exhaust = self._drive("exhaust_fan", self._fan_auto, None, first((hot or dead, "I-5")))

        target_temp = room_temp + (9.0 if lights else 0.5) - (4.0 if exhaust and lights else 0.0)
        target_rh = room_rh + (8.0 if exhaust else 28.0)
        self.air_temp = approach(self.air_temp, target_temp, dt_s, 900)
        self.air_rh = approach(self.air_rh, target_rh, dt_s, 600)

        # Pots dry out slowly, faster while the lights are on (plants drink more).
        drying = (0.14 if lights else 0.06) * dt_s / 86400
        self.soil = [max(0.0, level - drying) for level in self.soil]
        # Soil watering pumps: I-10 leak, I-12 tank low, never in fallback.
        block = first((leak, "I-10"), (self.tank_low, "I-12"), (self.fallback, "fallback"))
        for i in range(len(self.soil)):
            ran = self._dose(f"water_{i + 1}", block, dt_s)
            self.soil[i] = min(1.0, self.soil[i] + 0.02 * ran)  # ~2 % per second of pumping

        if self.has_tower:
            self._seconds += dt_s
            self.tower_temp = approach(self.tower_temp, self.air_temp, dt_s, 7200)
            cycle = lights and c.cycle_on(self._seconds, n["tower_on_s"], n["tower_off_s"])
            self._drive("tower_pump", cycle, first((leak, "I-10"), (self.tower_low, "I-7")), None)

    def entities(self) -> list[Entity]:
        lux = 32000.0 if self.state["lights"] else 0.0
        out: list[Entity] = [
            ("sensor", "air_temp", self._noisy(self.air_temp, 0.05, 2)),
            ("sensor", "air_rh", self._noisy(self.air_rh, 0.2, 1)),
            ("sensor", "light_lux", self._noisy(lux, 150.0 if lux else 0.0, 0)),
            ("binary_sensor", "leak", on_off(self.leak)),
        ]
        for i, level in enumerate(self.soil):
            level = 0.0 if i in self.soil_unplugged else level
            volts = self.SOIL_DRY_V - level * (self.SOIL_DRY_V - self.SOIL_WET_V)
            out.append(("sensor", f"soil_{i + 1}", self._noisy(volts, 0.004, 3)))
        if self.soil:
            out.append(("binary_sensor", "water_tank_low", on_off(self.tank_low)))
        if self.has_tower:
            out += [
                ("sensor", "tower_temp", self._noisy(self.tower_temp, 0.03, 2)),
                ("binary_sensor", "tower_low", on_off(self.tower_low)),
            ]
        return out + self.control_entities()


class WaterModel(NodeModel):
    """RDWC control bucket: heater thermostat, slowly falling level, pumps, room sensor."""

    devices = ("water_heater", "air_pump", "rdwc_pump")
    limits = {"water_setpoint": (15, 24)}
    CAPACITY_L = 60.0
    LOW_L = 20.0
    HIGH_L = 58.0

    def __init__(self, seed: int = 0) -> None:
        super().__init__(seed)
        self.numbers = {"water_setpoint": 20}
        self.add_doser("top_off", c.Doser(120, 300, 12))
        self.res_temp = 19.0
        self.liters = 50.0
        self.leak_res = False
        self.leak_topoff = False
        self.room_temp, self.room_rh = room_conditions(12)
        self._heat_auto = False
        self._sensor_dead = c.Held()
        self._low_held = c.Held()
        # Water chemistry, and what the probes are currently dipped in (None = the reservoir).
        self.ph = 6.1
        self.ec = 1500.0  # µS/cm
        self.ph_probe_in: float | None = None  # a buffer solution's pH
        self.ec_probe_in: float | None = None  # a calibration solution's EC

    @property
    def res_low(self) -> bool:
        return self.liters < self.LOW_L

    @property
    def res_high(self) -> bool:
        return self.liters >= self.HIGH_L

    def fault(self, text: str) -> bool:
        if text in ("leak on", "leak off"):
            self.leak_res = text.endswith("on")
            return True
        if text == "drain":
            self.liters = self.LOW_L - 2
            return True
        word, _, arg = text.partition(" ")
        if word in ("ph_buffer", "ec_solution", "ph_set", "ec_set"):
            try:
                value = None if arg == "off" else float(arg)
            except ValueError:
                return False
            if word == "ph_buffer":
                self.ph_probe_in = value  # probe moved into a buffer (or back with "off")
            elif word == "ec_solution":
                self.ec_probe_in = value
            elif value is not None and word == "ph_set":
                self.ph = value
            elif value is not None:
                self.ec = value
            return True
        return super().fault(text)

    def step(self, dt_s: float, hour: float) -> None:
        self.room_temp, self.room_rh = room_conditions(hour)
        temp = math.nan if self.sensor_fail else self.res_temp
        leak = self.leak_res or self.leak_topoff or self.hub_leak

        # Heater: I-3 sensor dead for 90 s, I-1 reservoir low, I-2 above 26 °C.
        self._heat_auto = c.heat_demand(self._heat_auto, temp, self.numbers["water_setpoint"], 0.5)
        dead = self._sensor_dead.update(math.isnan(temp), dt_s, 90)
        hot = not math.isnan(temp) and temp > 26.0
        heat_block = first((dead, "I-3"), (self.res_low, "I-1"), (hot, "I-2"))
        heater = self._drive("water_heater", self._heat_auto, heat_block, None)

        self._drive("air_pump", True, None, None)  # leaks do not stop the air pump

        # Circulation: I-10 leak, I-8 reservoir low for 10 s.
        low = self._low_held.update(self.res_low, dt_s, 10)
        self._drive("rdwc_pump", True, first((leak, "I-10"), (low, "I-8")), None)

        # Top-off: on request only. I-10 leak, I-9 full, never in fallback.
        fill_block = first((leak, "I-10"), (self.res_high, "I-9"), (self.fallback, "fallback"))
        ran = self._dose("top_off", fill_block, dt_s)

        heat_target = self.room_temp + (8.0 if heater else 0.0)
        self.res_temp = approach(self.res_temp, heat_target, dt_s, 10800)
        self.liters -= 1.5 * dt_s / 86400  # plants drink ~1.5 L/day
        self.liters += 2.0 * ran / 60  # top-off pump: 2 L/min
        self.liters = max(0.0, min(self.CAPACITY_L, self.liters))
        # Left alone, pH creeps up and the plants use up the nutrients.
        self.ph = min(8.5, self.ph + 0.15 * dt_s / 86400)
        self.ec = max(100.0, self.ec - 40.0 * dt_s / 86400)

    def _probe_ph(self) -> float:
        return self.ph if self.ph_probe_in is None else self.ph_probe_in

    def _probe_ec_volts(self) -> float:
        ec = self.ec if self.ec_probe_in is None else self.ec_probe_in
        return tds_volts(ec) * (1 + 0.02 * (self.res_temp - 25.0))

    def entities(self) -> list[Entity]:
        return [
            ("sensor", "res_temp", self._noisy(self.res_temp, 0.03, 2)),
            ("sensor", "room_temp", self._noisy(self.room_temp, 0.05, 2)),
            ("sensor", "room_rh", self._noisy(self.room_rh, 0.2, 1)),
            # Cheap analog probes: raw volts. pH boards read HIGHER volts for LOWER pH;
            # the TDS board's volts rise with conductivity and with temperature.
            ("sensor", "ph", self._noisy(2.5 + (7.0 - self._probe_ph()) * 0.18, 0.002, 3)),
            ("sensor", "ec", self._noisy(self._probe_ec_volts(), 0.003, 3)),
            ("binary_sensor", "res_low", on_off(self.res_low)),
            ("binary_sensor", "res_high", on_off(self.res_high)),
            ("binary_sensor", "leak_res", on_off(self.leak_res)),
            ("binary_sensor", "leak_topoff", on_off(self.leak_topoff)),
        ] + self.control_entities()


def build_models(seed: int = 0) -> dict[str, NodeModel]:
    """The default garden: two 4x4 tents (soil pots in tent 2), the tower tent, the water node."""
    return {
        "tent1": TentModel(seed + 1),
        "tent2": TentModel(seed + 2, soil_pots=4),
        "tent3": TentModel(seed + 3, has_tower=True),
        "water": WaterModel(seed + 4),
    }
