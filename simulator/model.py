"""Pure simulation models (no MQTT, no clocks) so behaviour is unit-testable.

Each model mimics what the real ESPHome node will do on its own: local schedules,
thermostats and the simplest interlocks from docs/SAFETY.md. The numbers are only
meant to look plausible on the dashboard, not to be accurate physics.
"""

from __future__ import annotations

import math
import random

Entity = tuple[str, str, str]  # (component, entity id, payload)


def approach(current: float, target: float, dt_s: float, tau_s: float) -> float:
    """Move `current` toward `target` with time constant `tau_s` (first-order lag)."""
    return target + (current - target) * math.exp(-dt_s / tau_s)


def on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def room_conditions(hour: float) -> tuple[float, float]:
    """Basement air (°C, %RH): steady, with a small daily swing."""
    phase = 2 * math.pi * (hour - 9) / 24
    return 18.0 + 1.0 * math.sin(phase), 50.0 - 4.0 * math.sin(phase)


class NodeModel:
    """Shared behaviour: switches with manual override, faults, published entities."""

    switches: tuple[str, ...] = ()

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.manual: dict[str, bool] = {}  # switch -> commanded state
        self.state: dict[str, bool] = dict.fromkeys(self.switches, False)
        self.fallback = False  # True when the hub heartbeat is missing
        self.sensor_fail = False

    def command(self, switch: str, value: bool) -> bool:
        """Apply an ON/OFF command. Returns False for an unknown switch."""
        if switch not in self.switches:
            return False
        self.manual[switch] = value
        return True

    def _resolve(self, switch: str, auto: bool) -> bool:
        """Manual command wins in NORMAL mode; FALLBACK ignores commands (SAFETY.md §2)."""
        if self.fallback or switch not in self.manual:
            return auto
        return self.manual[switch]

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

    def switch_entities(self) -> list[Entity]:
        return [("switch", name, on_off(self.state[name])) for name in self.switches]


class TentModel(NodeModel):
    """A grow tent: lights heat it, plants humidify it, the exhaust fan fixes both."""

    def __init__(self, seed: int = 0, has_tower: bool = False) -> None:
        self.has_tower = has_tower
        self.switches = ("lights", "exhaust_fan") + (("tower_pump",) if has_tower else ())
        super().__init__(seed)
        self.air_temp = 21.0
        self.air_rh = 60.0
        self.tower_temp = 19.0
        self.leak = False
        self.tower_low = False
        self._exhaust_auto = False

    def fault(self, text: str) -> bool:
        if text in ("leak on", "leak off"):
            self.leak = text.endswith("on")
            return True
        if self.has_tower and text in ("tower_low on", "tower_low off"):
            self.tower_low = text.endswith("on")
            return True
        return super().fault(text)

    def step(self, dt_s: float, hour: float) -> None:
        room_temp, room_rh = room_conditions(hour)
        lights = self._resolve("lights", 6 <= hour < 22)

        # Exhaust with hysteresis so it does not chatter around the threshold.
        if self.air_temp > 28 or self.air_rh > 70:
            self._exhaust_auto = True
        elif self.air_temp < 26 and self.air_rh < 60:
            self._exhaust_auto = False
        exhaust = self._resolve("exhaust_fan", self._exhaust_auto)

        target_temp = room_temp + (9.0 if lights else 0.5) - (4.0 if exhaust and lights else 0.0)
        target_rh = room_rh + (8.0 if exhaust else 28.0)
        self.air_temp = approach(self.air_temp, target_temp, dt_s, 900)
        self.air_rh = approach(self.air_rh, target_rh, dt_s, 600)
        self.state["lights"] = lights
        self.state["exhaust_fan"] = exhaust

        if self.has_tower:
            self.tower_temp = approach(self.tower_temp, self.air_temp, dt_s, 7200)
            cycle = lights and (hour * 60) % 60 < 15  # 15 min on / 45 min off, lights-on only
            pump = self._resolve("tower_pump", cycle)
            # Interlocks I-7 / I-10: never pump a dry reservoir or into a leak.
            self.state["tower_pump"] = pump and not self.tower_low and not self.leak

    def entities(self) -> list[Entity]:
        lux = 32000.0 if self.state["lights"] else 0.0
        out: list[Entity] = [
            ("sensor", "air_temp", self._noisy(self.air_temp, 0.05, 2)),
            ("sensor", "air_rh", self._noisy(self.air_rh, 0.2, 1)),
            ("sensor", "light_lux", self._noisy(lux, 150.0 if lux else 0.0, 0)),
            ("binary_sensor", "leak", on_off(self.leak)),
        ]
        if self.has_tower:
            out += [
                ("sensor", "tower_temp", self._noisy(self.tower_temp, 0.03, 2)),
                ("binary_sensor", "tower_low", on_off(self.tower_low)),
            ]
        return out + self.switch_entities()


class WaterModel(NodeModel):
    """RDWC control bucket: heater thermostat, slowly falling level, pumps, room sensor."""

    switches = ("water_heater", "air_pump", "rdwc_pump", "top_off")
    CAPACITY_L = 60.0
    LOW_L = 20.0
    HIGH_L = 58.0

    def __init__(self, seed: int = 0) -> None:
        super().__init__(seed)
        self.res_temp = 19.0
        self.liters = 50.0
        self.leak_res = False
        self.leak_topoff = False
        self.room_temp, self.room_rh = room_conditions(12)
        self._heater_auto = False

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
        return super().fault(text)

    def step(self, dt_s: float, hour: float) -> None:
        self.room_temp, self.room_rh = room_conditions(hour)
        leak = self.leak_res or self.leak_topoff

        if self.res_temp < 19.5:
            self._heater_auto = True
        elif self.res_temp > 20.5:
            self._heater_auto = False
        # Interlocks I-1 / I-2 / I-3: no heat when low, too hot, or the sensor is dead.
        heater = (
            self._resolve("water_heater", self._heater_auto)
            and not self.res_low
            and self.res_temp <= 26
            and not self.sensor_fail
        )
        # Interlocks I-9 / I-10: top-off only on command, never past full or into a leak.
        top_off = self._resolve("top_off", False) and not self.res_high and not leak
        # Interlocks I-8 / I-10. The air pump always runs.
        rdwc = self._resolve("rdwc_pump", True) and not self.res_low and not leak

        heat_target = self.room_temp + (8.0 if heater else 0.0)
        self.res_temp = approach(self.res_temp, heat_target, dt_s, 10800)
        self.liters -= 1.5 * dt_s / 86400  # plants drink ~1.5 L/day
        if top_off:
            self.liters += 2.0 * dt_s / 60
        self.liters = max(0.0, min(self.CAPACITY_L, self.liters))

        self.state.update(water_heater=heater, air_pump=True, rdwc_pump=rdwc, top_off=top_off)

    def entities(self) -> list[Entity]:
        return [
            ("sensor", "res_temp", self._noisy(self.res_temp, 0.03, 2)),
            ("sensor", "room_temp", self._noisy(self.room_temp, 0.05, 2)),
            ("sensor", "room_rh", self._noisy(self.room_rh, 0.2, 1)),
            ("binary_sensor", "res_low", on_off(self.res_low)),
            ("binary_sensor", "res_high", on_off(self.res_high)),
            ("binary_sensor", "leak_res", on_off(self.leak_res)),
            ("binary_sensor", "leak_topoff", on_off(self.leak_topoff)),
        ] + self.switch_entities()


def build_models(seed: int = 0) -> dict[str, NodeModel]:
    """The default garden: two 4x4 tents, the tower tent, and the water node."""
    return {
        "tent1": TentModel(seed + 1),
        "tent2": TentModel(seed + 2),
        "tent3": TentModel(seed + 3, has_tower=True),
        "water": WaterModel(seed + 4),
    }
