"""Automatic soil watering, strictly under docs/SAFETY.md §4b.

The failure this is built around: a moisture sensor that reads "dry" forever (fallen out
of the pot, unplugged, broken) while the pump keeps answering it. So the hub waters in
small fixed doses, waits for the water to soak in, and demands that the reading actually
rises. Two doses without a rise and it stops and asks for a human.

The node enforces its own hard limits as well (firmware Doser: run time, rest, daily cap,
tank low, leak, no hub). Everything here is the hub's layer on top.
"""

from __future__ import annotations

import sqlite3

from .calibration import Calibrations
from .config import SiteConfig, WateringPot
from .control import Controller, Refused
from .state import LiveState

FRESH_S = 300  # a moisture reading older than this is not acted on
DAY_S = 86400
REASONS = {
    "no_response": "watered twice but the soil did not get wetter "
    "(empty tank, blocked tube, or the sensor is out of the soil)",
    "daily_cap": "reached the maximum number of doses in 24 hours",
}


class Watering:
    def __init__(
        self,
        conn: sqlite3.Connection,
        site: SiteConfig,
        live: LiveState,
        calibrations: Calibrations,
        controller: Controller,
    ) -> None:
        self.conn = conn
        self.cfg = site.watering
        self.live = live
        self.cal = calibrations
        self.controller = controller
        self.pots: dict[str, WateringPot] = {p.sensor: p for p in self.cfg.pots}
        for key in self.pots:
            conn.execute("INSERT OR IGNORE INTO watering_pot (sensor_key) VALUES (?)", (key,))
        conn.commit()

    # ------------------------------------------------------------ stored state
    def _row(self, key: str) -> sqlite3.Row:
        return self.conn.execute(
            "SELECT mode, strikes, locked, judged_ts FROM watering_pot WHERE sensor_key = ?",
            (key,),
        ).fetchone()

    def _update(self, key: str, **fields) -> None:
        sets = ", ".join(f"{name} = ?" for name in fields)
        self.conn.execute(
            f"UPDATE watering_pot SET {sets} WHERE sensor_key = ?", (*fields.values(), key)
        )
        self.conn.commit()
        self.controller.changed = True

    def set_mode(self, key: str, mode: str) -> None:
        if key not in self.pots or mode not in ("off", "auto"):
            raise Refused("Unknown pot or mode.")
        if mode == "auto" and not self.cal.is_calibrated(key):
            raise Refused("Calibrate this pot's sensor before turning on auto-watering.")
        self._update(key, mode=mode)

    def unlock(self, key: str) -> None:
        if key not in self.pots:
            raise Refused("Unknown pot.")
        self._update(key, locked=None, strikes=0)

    # ------------------------------------------------------------ readings
    def _moisture(self, key: str, now: float) -> float | None:
        """Current moisture %, or None unless the reading is fresh, calibrated and plausible."""
        entry = self.live.values.get(key)
        if entry is None or now - entry["ts"] > FRESH_S:
            return None
        unclamped = self.cal.raw_percent(key, entry.get("raw"))
        # More than 10 % outside the calibrated range means the sensor is not in soil.
        if unclamped is None or not -10 <= unclamped <= 110:
            return None
        return entry["value"]

    def _blocked(self, pot: WateringPot, now: float) -> str | None:
        """Why no dose may be given right now (applies to manual and automatic doses)."""
        if self.controller.leak_alarm:
            return "leak alarm active"
        tank = self.live.values.get(pot.tank_low)
        if tank is None or tank["value"] is not False:
            return "watering tank is low or its sensor is not reporting"
        last = self.controller.last_dose(pot.pump)
        if last is not None and now - last["ts"] < self.cfg.soak_s:
            return "waiting for the last dose to soak in"
        if self.controller.doses_since(pot.pump, now - DAY_S) >= self.cfg.max_doses_per_day:
            return "daily dose limit reached"
        return None

    # ------------------------------------------------------------ actions
    async def water_now(self, key: str, now: float) -> None:
        """One manual dose. Obeys every limit except the moisture threshold."""
        pot = self.pots.get(key)
        if pot is None:
            raise Refused("Unknown pot.")
        reason = self._blocked(pot, now)
        if reason:
            raise Refused(f"Not watering: {reason}.")
        await self.controller.dose(pot.pump, "manual", now, self._moisture(key, now))

    def _judge_last_dose(self, key: str, pot: WateringPot, now: float) -> None:
        """Once a dose has soaked in, check the soil actually got wetter."""
        last = self.controller.last_dose(pot.pump)
        if last is None or self._row(key)["judged_ts"] >= last["ts"]:
            return
        if now - last["ts"] < self.cfg.soak_s:
            return
        # Remembered in the database so a hub restart cannot judge the same dose twice.
        self._update(key, judged_ts=last["ts"])
        if last["pre_value"] is None:
            return  # a manual dose given without a usable reading: nothing to compare
        value = self._moisture(key, now)
        if value is not None and value - last["pre_value"] >= self.cfg.min_rise:
            self._update(key, strikes=0)
            return
        strikes = self._row(key)["strikes"] + 1
        if strikes >= self.cfg.max_strikes:
            self._update(key, strikes=strikes, locked="no_response")
        else:
            self._update(key, strikes=strikes)

    async def tick(self, now: float) -> None:
        for key, pot in self.pots.items():
            self._judge_last_dose(key, pot, now)
            row = self._row(key)
            if row["mode"] != "auto" or row["locked"]:
                continue
            value = self._moisture(key, now)
            if value is None or value >= pot.below:
                continue
            reason = self._blocked(pot, now)
            if reason == "daily dose limit reached":
                self._update(key, locked="daily_cap")
            if reason:
                continue
            await self.controller.dose(pot.pump, "auto", now, value)

    # ------------------------------------------------------------ for the GUI and alerts
    def locked_reason(self, key: str) -> str | None:
        locked = self._row(key)["locked"]
        return REASONS.get(locked, locked) if locked else None

    def status(self, now: float) -> list[dict]:
        out = []
        for key, pot in self.pots.items():
            row = self._row(key)
            last = self.controller.last_dose(pot.pump)
            out.append(
                {
                    "sensor": key,
                    "pump": pot.pump,
                    "name": pot.name,
                    "below": pot.below,
                    "mode": row["mode"],
                    "locked": self.locked_reason(key),
                    "blocked": self._blocked(pot, now),
                    "last_dose": last["ts"] if last else None,
                    "doses_24h": self.controller.doses_since(pot.pump, now - DAY_S),
                    "max_doses": self.cfg.max_doses_per_day,
                }
            )
        return out
