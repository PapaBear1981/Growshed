"""Python port of firmware/common/control.h, so simulated nodes behave like real ones.

The C++ header is the real thing (and has its own tests). Keep this file in step with it:
same names, same rules, same order of precedence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MODES = ("auto", "on", "off")


@dataclass(frozen=True)
class Decision:
    on: bool
    source: str  # auto | manual | fallback | interlock
    interlock: str | None = None


def decide(mode: str, fallback: bool, auto_on: bool, block: str | None, force: str | None):
    if fallback:
        want, source = auto_on, "fallback"
    elif mode == "on":
        want, source = True, "manual"
    elif mode == "off":
        want, source = False, "manual"
    else:
        want, source = auto_on, "auto"
    if block is not None:
        return Decision(False, "interlock", block) if want else Decision(False, source)
    if force is not None and not want:
        return Decision(True, "interlock", force)
    return Decision(want, source)


def in_window(now_min: int, on_min: int, off_min: int) -> bool:
    if on_min == off_min:
        return False
    if on_min < off_min:
        return on_min <= now_min < off_min
    return now_min >= on_min or now_min < off_min


def heat_demand(was_on: bool, temp: float, setpoint: float, band: float) -> bool:
    if math.isnan(temp):
        return was_on
    if temp < setpoint - band:
        return True
    if temp > setpoint + band:
        return False
    return was_on


def exhaust_demand(was_on: bool, temp: float, rh: float, max_temp: float, max_rh: float) -> bool:
    temp_ok, rh_ok = not math.isnan(temp), not math.isnan(rh)
    if (temp_ok and temp > max_temp) or (rh_ok and rh > max_rh):
        return True
    if (not temp_ok or temp < max_temp - 2) and (not rh_ok or rh < max_rh - 5):
        return False
    return was_on


def cycle_on(seconds: float, on_s: float, off_s: float) -> bool:
    if on_s <= 0:
        return False
    if off_s <= 0:
        return True
    return seconds % (on_s + off_s) < on_s


class Held:
    def __init__(self) -> None:
        self.seconds = 0.0

    def update(self, condition: bool, dt_s: float, hold_s: float) -> bool:
        if not condition:
            self.seconds = 0.0
            return False
        self.seconds = min(hold_s, self.seconds + dt_s)
        return self.seconds >= hold_s


class OverTemp:
    def __init__(self) -> None:
        self.tripped = False
        self.above = Held()

    def update(self, temp: float, trip: float, clear: float, dt_s: float, hold_s: float) -> bool:
        if math.isnan(temp):
            self.above.update(False, dt_s, hold_s)
            return self.tripped
        if self.above.update(temp > trip, dt_s, hold_s):
            self.tripped = True
        if self.tripped and temp < clear:
            self.tripped = False
        return self.tripped


class Doser:
    def __init__(self, max_s: float, rest_s: float, max_per_day: int) -> None:
        self.max_s, self.rest_s, self.max_per_day = max_s, rest_s, max_per_day
        self.remaining = self.resting = self.window = 0.0
        self.count = 0
        self.refused: str | None = None

    def step(self, request_s: float, block: str | None, dt_s: float) -> float:
        """Returns how many seconds the pump ran during this step (0 if it did not)."""
        self.window += dt_s
        if self.window >= 86400:
            self.window, self.count = 0.0, 0
        self.resting = max(0.0, self.resting - dt_s)
        if request_s > 0:
            if block is not None:
                self.refused = block
            elif self.remaining > 0 or self.resting > 0:
                self.refused = "busy"
            elif self.count >= self.max_per_day:
                self.refused = "daily-cap"
            else:
                self.remaining = min(request_s, self.max_s)
                self.resting = self.rest_s
                self.count += 1
                self.refused = None
        if self.remaining > 0 and block is not None:
            self.remaining = 0.0
            self.refused = block
        ran = min(self.remaining, dt_s) if self.remaining > 0 else 0.0
        self.remaining -= ran
        return ran

    def status(self, on: bool) -> str:
        return "dosing" if on else ("refused" if self.refused else "idle")


class MlDoser:
    """Port of gs::MlDoser: a chemical dosing pump, in millilitres and milliseconds."""

    MAX_RUN_MS = 60000

    def __init__(self, max_ml: float, max_day_ml: float, rest_ms: float) -> None:
        self.max_ml, self.max_day_ml, self.rest_ms = max_ml, max_day_ml, rest_ms
        self.remaining_ms = self.resting_ms = self.window_ms = 0.0
        self.day_ml = 0.0
        self.refused: str | None = None

    def step(self, request_ml: float, ml_per_s: float, block: str | None, dt_ms: float) -> float:
        """Returns how many milliseconds the pump ran during this step."""
        self.window_ms += dt_ms
        if self.window_ms >= 86400000:
            self.window_ms, self.day_ml = 0.0, 0.0
        self.resting_ms = max(0.0, self.resting_ms - dt_ms)
        if request_ml > 0:
            ml = min(request_ml, self.max_ml)
            if block is not None:
                self.refused = block
            elif not ml_per_s > 0:
                self.refused = "uncalibrated"
            elif self.remaining_ms > 0 or self.resting_ms > 0:
                self.refused = "busy"
            elif self.day_ml + ml > self.max_day_ml:
                self.refused = "daily-cap"
            else:
                self.remaining_ms = min(ml / ml_per_s * 1000, self.MAX_RUN_MS)
                self.resting_ms = self.rest_ms
                self.day_ml += ml
                self.refused = None
        if self.remaining_ms > 0 and block is not None:
            self.remaining_ms = 0.0
            self.refused = block
        ran = min(self.remaining_ms, dt_ms) if self.remaining_ms > 0 else 0.0
        self.remaining_ms -= ran
        return ran

    def status(self, on: bool) -> str:
        return "dosing" if on else ("refused" if self.refused else "idle")


class Primer:
    def __init__(self) -> None:
        self.remaining_ms = 0.0

    def step(self, request_s: float, max_s: float, block: str | None, dt_ms: float) -> float:
        if block is not None:
            self.remaining_ms = 0.0
            return 0.0
        if request_s > 0 and self.remaining_ms <= 0:
            self.remaining_ms = 1000 * min(request_s, max_s)
        ran = min(self.remaining_ms, dt_ms) if self.remaining_ms > 0 else 0.0
        self.remaining_ms -= ran
        return ran
