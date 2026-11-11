"""Automatic pH and nutrient dosing (Phase 4), strictly under docs/SAFETY.md §4.

Wrong dosing can kill every plant in the reservoir overnight, and this system uses cheap
probes. So the design is defensive at every step:

- Three modes. OFF (the default). SUGGEST: the hub proposes one small dose and a person
  approves it. AUTO: the hub doses by itself, and only after a person explicitly turned
  that on and acknowledged the warning.
- One small dose, then a long wait for mixing, then a fresh measurement. Never a second
  dose based on a reading taken before the first one mixed in.
- A dose must show an effect. Two doses of the same kind with no movement in the right
  direction, and dosing stops for a human (empty bottle, air in the tube, dead probe).
- The hub will not act on a reading it cannot trust: uncalibrated or overdue probes,
  stale, unsteady or jumping readings, no circulation, low reservoir, any leak.
- The dosing node enforces its own hard limits on top (firmware: gs::MlDoser).
"""

from __future__ import annotations

import sqlite3
from collections import deque

from . import db, topics
from .calibration import MAX_AGE_DAYS, Calibrations
from .config import DosingConfig, SiteConfig
from .control import Controller, Refused
from .mqtt import MqttLink
from .state import LiveState

FRESH_S = 120
NODE_QUIET_S = 120
OPPOSING_S = 3600  # never pH up and pH down within the same hour
NUTRIENT_GAP_S = 60  # A first, then B
SNOOZE_S = 3600  # after "not now" on a suggestion
DISTRUST_S = 900  # after a reading jumps
RECENT_S = 300  # how far back "recent readings" go
MIN_READINGS = 3  # recent readings needed before any automatic decision
MAX_STRIKES = 2
KINDS = ("ph_down", "ph_up", "nutrients")
LABELS = {"ph_down": "pH down", "ph_up": "pH up", "nutrients": "Nutrients A + B",
          "nutrient_a": "Nutrient A", "nutrient_b": "Nutrient B"}  # fmt: skip
LOCK_REASONS = {
    "no_response": "two doses in a row had no effect "
    "(empty bottle, air in the tube, or a probe that is not reading the reservoir)",
    "daily_cap": "the daily limit for a pump was reached",
    "b_skipped": "nutrient A was dosed but nutrient B could not be: the mix is now uneven",
}


class Dosing:
    def __init__(
        self,
        conn: sqlite3.Connection,
        site: SiteConfig,
        live: LiveState,
        calibrations: Calibrations,
        controller: Controller,
        link: MqttLink,
        tunables=None,
    ) -> None:
        self.conn = conn
        self.cfg: DosingConfig = site.dosing
        self.site = site
        self.live = live
        self.cal = calibrations
        self.controller = controller
        self.link = link
        self.tunables = tunables  # targets and dose sizes changed in the GUI
        self.devices = {d.state_key: d for d in site.devices}
        self.suggestion: dict | None = None
        self.snoozed: dict[str, float] = {}
        self.pending_b: tuple[float, float, str] | None = None  # (due, mL, source)
        self.distrust_until = 0.0
        self._recent = {"ph": deque(maxlen=30), "ec": deque(maxlen=30)}
        self._last_seen_ts = {"ph": 0.0, "ec": 0.0}

    def target(self, name: str) -> float:
        """A target or dose size: the GUI's value if one was set, else config.yaml's."""
        if self.tunables is not None:
            return self.tunables.get(f"dosing.{name}")
        return getattr(self.cfg, name)

    # ------------------------------------------------------------ stored state
    @property
    def mode(self) -> str:
        return db.get_setting(self.conn, "dosing_mode", "off")

    @property
    def locked(self) -> str | None:
        return db.get_setting(self.conn, "dosing_locked", "") or None

    def _lock(self, reason: str) -> None:
        db.set_setting(self.conn, "dosing_locked", reason)
        self.suggestion = None
        self.controller.changed = True

    def unlock(self) -> None:
        db.set_setting(self.conn, "dosing_locked", "")
        for kind in KINDS:
            db.set_setting(self.conn, f"dosing_strikes_{kind}", "0")
        self.controller.changed = True

    def _strikes(self, kind: str) -> int:
        return int(db.get_setting(self.conn, f"dosing_strikes_{kind}", "0"))

    # ------------------------------------------------------------ what the hub can see
    def _value(self, key: str, now: float) -> float | None:
        entry = self.live.values.get(key)
        if entry is None or entry["value"] is None or now - entry["ts"] > FRESH_S:
            return None
        return entry["value"]

    def _node_alive(self, key: str, now: float) -> bool:
        info = self.live.nodes.get(key.split("/")[0])
        if info is None or info["status"] == "offline" or info["last_seen"] is None:
            return False
        return now - info["last_seen"] <= NODE_QUIET_S

    def pump_rate(self, pump: str) -> float:
        device = self.devices[self.cfg.pumps[pump]]
        entry = self.live.values.get(f"{device.node}/number/{device.key}_ml_per_s")
        return (entry or {}).get("value") or 0.0

    def _observe(self, now: float) -> None:
        """Track recent readings to spot unsteady or jumping probes (cheap-probe rule)."""
        limits = {"ph": lambda old, new: abs(new - old) > 0.5,
                  "ec": lambda old, new: old > 0 and abs(new - old) / old > 0.30}  # fmt: skip
        for name, key in (("ph", self.cfg.ph_sensor), ("ec", self.cfg.ec_sensor)):
            entry = self.live.values.get(key)
            if entry is None or entry["value"] is None or entry["ts"] <= self._last_seen_ts[name]:
                continue
            self._last_seen_ts[name] = entry["ts"]
            recent = self._recent[name]
            sudden = bool(recent) and entry["ts"] - recent[-1][0] <= RECENT_S
            if (
                sudden
                and limits[name](recent[-1][1], entry["value"])
                and not self._dosed_within(now, self.cfg.wait_s)
            ):
                # A sudden jump that no dose explains: bumped probe, bubble, electrical noise.
                self.distrust_until = now + DISTRUST_S
            recent.append((entry["ts"], entry["value"]))

    def _steadiness(self, now: float) -> str | None:
        """None if the last few minutes of readings agree, else why they cannot be trusted."""
        ph = [v for ts, v in self._recent["ph"] if now - ts <= RECENT_S]
        ec = [v for ts, v in self._recent["ec"] if now - ts <= RECENT_S]
        if len(ph) < MIN_READINGS or len(ec) < MIN_READINGS:
            # Never act on a single reading, e.g. the first one after the hub starts.
            return "collecting readings"
        if max(ph) - min(ph) > 0.3 or (min(ec) > 0 and (max(ec) - min(ec)) / min(ec) > 0.15):
            return "the readings are unsteady"
        return None

    # ------------------------------------------------------------ dose history
    def _last(self, where: str = "1=1", args: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(
            f"SELECT * FROM chem_dose WHERE {where} ORDER BY ts DESC, id DESC LIMIT 1", args
        ).fetchone()

    def _dosed_within(self, now: float, seconds: float) -> bool:
        last = self._last()
        return last is not None and now - last["ts"] < seconds

    def day_ml(self, pump: str, now: float) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(ml), 0) AS total FROM chem_dose WHERE pump = ? AND ts > ?",
            (pump, int(now - 86400)),
        ).fetchone()
        return row["total"]

    # ------------------------------------------------------------ the checks
    def blocked(self, now: float, need_probes: bool = True) -> str | None:
        """Why nothing may be dosed right now, or None. Manual doses skip the probe checks."""
        cfg = self.cfg
        if self.locked:
            return "dosing is stopped: " + LOCK_REASONS.get(self.locked, self.locked)
        if self.controller.leak_alarm:
            return "the leak alarm is active"
        if not self._node_alive(cfg.ph_down, now):
            return "the dosing node is offline"
        if not self._node_alive(cfg.circulation, now):
            return "the water node is offline"
        if (self.live.values.get(cfg.circulation) or {}).get("value") is not True:
            return "the circulation pump is off (doses would not mix)"
        if (self.live.values.get(cfg.level_low) or {}).get("value") is not False:
            return "the reservoir is low or its level sensor is not reporting"
        if self.pending_b is not None:
            return "nutrient B is about to be dosed"
        if self._dosed_within(now, cfg.wait_s):
            return "waiting for the last dose to mix in"
        if not need_probes:
            return None
        for name, key, kind in (("pH", cfg.ph_sensor, "ph"), ("EC", cfg.ec_sensor, "ec")):
            if not self.cal.is_calibrated(key):
                return f"the {name} probe is not calibrated"
            age = self.cal.age_days(key, now)
            if age is not None and age > MAX_AGE_DAYS[kind]:
                return f"the {name} calibration is {age:.0f} days old (limit {MAX_AGE_DAYS[kind]})"
            if self._value(key, now) is None:
                return f"no fresh {name} reading"
        if now < self.distrust_until:
            return "a reading jumped suddenly; waiting to see whether it is real"
        return self._steadiness(now)

    def _kind_blocked(self, kind: str, ml: float, now: float) -> str | None:
        """Limits that apply to one kind of dose. May lock dosing (daily cap)."""
        pumps = ["nutrient_a", "nutrient_b"] if kind == "nutrients" else [kind]
        for pump in pumps:
            if self.pump_rate(pump) <= 0:
                return f"the {LABELS[pump]} pump has not been calibrated"
            if self.day_ml(pump, now) + ml > self.cfg.max_day_ml:
                self._lock("daily_cap")
                return "dosing is stopped: " + LOCK_REASONS["daily_cap"]
        opposite = {"ph_down": "ph_up", "ph_up": "ph_down"}.get(kind)
        if opposite:
            last = self._last("pump = ?", (opposite,))
            if last is not None and now - last["ts"] < OPPOSING_S:
                return f"{LABELS[opposite]} was dosed less than an hour ago"
        return None

    def need(self, now: float) -> tuple[str, float, str] | None:
        """What the reservoir needs most: (kind, mL, why). Nutrients first: they shift pH."""
        cfg = self.cfg
        ph, ec = self._value(cfg.ph_sensor, now), self._value(cfg.ec_sensor, now)
        if ph is None or ec is None:
            return None
        ph_low, ph_high, ec_low = (self.target(n) for n in ("ph_low", "ph_high", "ec_low"))
        if ec < ec_low:
            why = f"EC is {ec / 1000:.2f} mS/cm, below {ec_low / 1000:.2f}"
            return "nutrients", self.target("nutrient_dose_ml"), why
        if ph > ph_high:
            return "ph_down", self.target("ph_dose_ml"), f"pH is {ph:.1f}, above {ph_high:.1f}"
        if ph < ph_low:
            return "ph_up", self.target("ph_dose_ml"), f"pH is {ph:.1f}, below {ph_low:.1f}"
        return None

    # ------------------------------------------------------------ dosing
    async def _send(self, pump: str, kind: str, ml: float, source: str, now: float) -> None:
        device = self.devices[self.cfg.pumps[pump]]
        await self.link.publish(
            f"{topics.PREFIX}/{device.node}/dose/{device.key}/command", f"{ml:g}"
        )
        self.conn.execute(
            "INSERT INTO chem_dose (ts, kind, pump, ml, source, ph_before, ec_before) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(now), kind, pump, ml, source,
             self._value(self.cfg.ph_sensor, now), self._value(self.cfg.ec_sensor, now)),
        )  # fmt: skip
        # Also into the hand-dosing log, so it appears on the Water page and the charts.
        self.conn.execute(
            "INSERT INTO dose_log (ts, zone, product, amount, unit, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(now), self.cfg.zone, LABELS[pump], ml, "mL", f"dosing pump ({source})"),
        )
        self.conn.commit()
        self.controller.changed = True

    async def _execute(self, kind: str, ml: float, source: str, now: float) -> None:
        self.suggestion = None
        if kind == "nutrients":
            # Equal amounts, A first, B a minute later (SAFETY.md §4).
            await self._send("nutrient_a", kind, ml, source, now)
            self.pending_b = (now + NUTRIENT_GAP_S, ml, source)
        else:
            await self._send(kind, kind, ml, source, now)

    async def _finish_nutrients(self, now: float) -> None:
        due, ml, source = self.pending_b
        if now < due:
            return
        self.pending_b = None
        problem = self.controller.leak_alarm or not self._node_alive(self.cfg.nutrient_b, now)
        if problem:
            self._lock("b_skipped")
            return
        await self._send("nutrient_b", "nutrients", ml, source, now)

    def _judge(self, now: float) -> None:
        """After the mixing wait, check that the last dose moved the reading the right way."""
        last = self._last("judged = 0 AND pump != 'nutrient_b'")
        if last is None or now - last["ts"] < self.cfg.wait_s:
            return
        self.conn.execute("UPDATE chem_dose SET judged = 1 WHERE ts <= ?", (last["ts"],))
        self.conn.commit()
        kind = last["kind"]
        ph, ec = self._value(self.cfg.ph_sensor, now), self._value(self.cfg.ec_sensor, now)
        if kind == "nutrients":
            worked = (
                None if last["ec_before"] is None or ec is None else ec > last["ec_before"] * 1.02
            )
        else:
            if last["ph_before"] is None or ph is None:
                worked = None
            elif kind == "ph_down":
                worked = ph < last["ph_before"] - 0.05
            else:
                worked = ph > last["ph_before"] + 0.05
        if worked is None:
            return  # no reading to compare (e.g. a manual dose without probes): cannot judge
        strikes = 0 if worked else self._strikes(kind) + 1
        db.set_setting(self.conn, f"dosing_strikes_{kind}", str(strikes))
        if strikes >= MAX_STRIKES:
            self._lock("no_response")

    async def tick(self, now: float) -> None:
        self._observe(now)
        if self.pending_b is not None:
            await self._finish_nutrients(now)
        self._judge(now)
        mode = self.mode
        if mode == "off":
            self.suggestion = None
            return
        need = None if self.blocked(now) else self.need(now)
        reason = self._kind_blocked(need[0], need[1], now) if need else None
        if need is None or reason is not None or now < self.snoozed.get(need[0], 0):
            if self.suggestion is not None:
                self.suggestion = None
                self.controller.changed = True
            return
        kind, ml, why = need
        if mode == "auto":
            await self._execute(kind, ml, "auto", now)
        elif self.suggestion is None or self.suggestion["kind"] != kind:
            self.suggestion = {"kind": kind, "label": LABELS[kind], "ml": ml, "why": why,
                               "since": int(now)}  # fmt: skip
            self.controller.changed = True
        else:
            self.suggestion["why"] = why

    # ------------------------------------------------------------ requests from people
    def set_mode(self, mode: str, acknowledged: bool, now: float) -> None:
        if mode not in ("off", "suggest", "auto"):
            raise Refused("Mode must be off, suggest or auto.")
        if mode == "auto" and not acknowledged:
            # The GUI shows the warning; the hub insists it was accepted.
            raise Refused(
                "Automatic dosing must be confirmed: incorrect dosing can kill the plants."
            )
        if mode != "off":
            missing = [LABELS[p] + " pump" for p in self.cfg.pumps if self.pump_rate(p) <= 0]
            probes = (("pH", self.cfg.ph_sensor), ("EC", self.cfg.ec_sensor))
            missing += [n + " probe" for n, k in probes if not self.cal.is_calibrated(k)]
            if missing:
                raise Refused("Calibrate first: " + ", ".join(missing) + ".")
        db.set_setting(self.conn, "dosing_mode", mode)
        self.suggestion = None
        self.controller.changed = True

    async def approve(self, now: float) -> None:
        """Carry out the current suggestion, after checking everything again."""
        if self.suggestion is None:
            raise Refused("There is no suggestion to approve any more.")
        reason = self.blocked(now)
        need = None if reason else self.need(now)
        if need is None or need[0] != self.suggestion["kind"]:
            self.suggestion = None
            self.controller.changed = True
            raise Refused(f"Not dosing: {reason or 'the reading is back in range'}.")
        reason = self._kind_blocked(need[0], need[1], now)
        if reason:
            raise Refused(f"Not dosing: {reason}.")
        await self._execute(need[0], need[1], "approved", now)

    def dismiss(self, now: float) -> None:
        if self.suggestion is not None:
            self.snoozed[self.suggestion["kind"]] = now + SNOOZE_S
            self.suggestion = None
            self.controller.changed = True

    async def manual(self, kind: str, now: float) -> None:
        """One dose chosen by a person. Every limit applies except the probe checks."""
        if kind not in KINDS:
            raise Refused("Unknown kind of dose.")
        ml = self.target("nutrient_dose_ml") if kind == "nutrients" else self.target("ph_dose_ml")
        reason = self.blocked(now, need_probes=False) or self._kind_blocked(kind, ml, now)
        if reason:
            raise Refused(f"Not dosing: {reason}.")
        await self._execute(kind, ml, "manual", now)

    async def prime(self, pump: str, seconds: float) -> None:
        if pump not in self.cfg.pumps or not 1 <= seconds <= 30:
            raise Refused("Choose a pump and 1 to 30 seconds.")
        if self.controller.leak_alarm:
            raise Refused("The leak alarm is active.")
        device = self.devices[self.cfg.pumps[pump]]
        await self.link.publish(
            f"{topics.PREFIX}/{device.node}/prime/{device.key}/command", f"{seconds:g}"
        )

    async def set_rate(self, pump: str, ml: float, seconds: float) -> None:
        """Store a pump's flow rate from a timed run into a measuring cup."""
        if pump not in self.cfg.pumps or seconds <= 0 or ml <= 0:
            raise Refused("Enter how many mL came out, and for how many seconds the pump ran.")
        rate = ml / seconds
        if not 0.05 <= rate <= 5:
            raise Refused(
                f"{rate:.2f} mL per second is not plausible for these pumps. Measure again."
            )
        device = self.devices[self.cfg.pumps[pump]]
        await self.link.publish(
            f"{topics.PREFIX}/{device.node}/number/{device.key}_ml_per_s/command", f"{rate:.3f}"
        )

    # ------------------------------------------------------------ for the GUI
    def snapshot(self, now: float) -> dict:
        cfg = self.cfg
        mode = self.mode
        return {
            "zone": cfg.zone,
            "mode": mode,
            "locked": LOCK_REASONS.get(self.locked, self.locked) if self.locked else None,
            "blocked": None if mode == "off" else self.blocked(now),
            "suggestion": self.suggestion,
            "targets": {n: self.target(n) for n in ("ph_low", "ph_high", "ec_low")},
            "doses": {
                "ph": self.target("ph_dose_ml"),
                "nutrients": self.target("nutrient_dose_ml"),
            },
            "max_day_ml": cfg.max_day_ml,
            "pumps": [
                {
                    "pump": p,
                    "label": LABELS[p],
                    "rate": self.pump_rate(p),
                    "day_ml": round(self.day_ml(p, now), 2),
                }
                for p in cfg.pumps
            ],  # fmt: skip
        }
