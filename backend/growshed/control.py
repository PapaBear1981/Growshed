"""Hub-side control: device modes, node settings, doses, and the house-wide leak alarm.

The hub never switches a relay itself. It asks a node for a mode (auto / on / off), a
setting, or a dose; the node applies its own interlocks before anything moves
(docs/SAFETY.md, firmware/common/control.h). So the worst a hub bug can do is ask for
something the node refuses.
"""

from __future__ import annotations

import sqlite3

from . import db, topics
from .config import Device, Setting, SiteConfig
from .mqtt import MqttLink
from .state import LiveState

MODES = ("auto", "on", "off")


class Refused(Exception):
    """A request that must not be carried out. The message is shown to the user."""


class Controller:
    def __init__(
        self, conn: sqlite3.Connection, site: SiteConfig, live: LiveState, link: MqttLink
    ) -> None:
        self.conn = conn
        self.site = site
        self.live = live
        self.link = link
        self.devices: dict[str, Device] = {d.state_key: d for d in site.devices}
        self.settings: dict[str, Setting] = {s.state_key: s for s in site.settings}
        self.leak_keys = [s.state_key for s in site.sensors if s.kind == "leak"]
        self.leak_alarm = db.get_setting(conn, "leak_alarm", "off") == "on"
        self.changed = False  # set when the GUI's control view needs refreshing

    # ------------------------------------------------------------ modes
    async def set_mode(self, key: str, mode: str, hours: float | None, now: float) -> None:
        device = self.devices.get(key)
        if device is None or device.control != "mode":
            raise Refused("That device has no auto/on/off mode.")
        if mode not in MODES:
            raise Refused("Mode must be auto, on or off.")
        await self.link.publish(self._topic(device.mode_key), mode)
        self.conn.execute("DELETE FROM device_override WHERE key = ?", (key,))
        if mode != "auto" and hours:
            self.conn.execute(
                "INSERT INTO device_override (key, mode, expires_at) VALUES (?, ?, ?)",
                (key, mode, int(now + hours * 3600)),
            )
        self.conn.commit()
        self.changed = True

    def overrides(self) -> dict[str, dict]:
        rows = self.conn.execute("SELECT key, mode, expires_at FROM device_override")
        return {r["key"]: {"mode": r["mode"], "expires_at": r["expires_at"]} for r in rows}

    async def _expire_overrides(self, now: float) -> None:
        rows = self.conn.execute(
            "SELECT key FROM device_override WHERE expires_at <= ?", (int(now),)
        ).fetchall()
        for row in rows:
            device = self.devices.get(row["key"])
            if device is not None:
                # If this publish fails (broker down) the row stays and we retry next tick.
                await self.link.publish(self._topic(device.mode_key), "auto")
            self.conn.execute("DELETE FROM device_override WHERE key = ?", (row["key"],))
            self.conn.commit()
            self.changed = True

    # ------------------------------------------------------------ settings and doses
    async def set_number(self, key: str, value: float) -> None:
        setting = self.settings.get(key)
        if setting is None:
            raise Refused("Unknown setting.")
        if not setting.min <= value <= setting.max:
            raise Refused(f"{setting.name} must be between {setting.min:g} and {setting.max:g}.")
        await self.link.publish(self._topic(key), f"{value:g}")

    async def dose(self, key: str, source: str, now: float, pre_value: float | None = None) -> None:
        """Ask a dose pump to run for its configured time. The node may still refuse."""
        device = self.devices.get(key)
        if device is None or device.control != "dose":
            raise Refused("That device is not a dose pump.")
        if self.leak_alarm:
            raise Refused("The leak alarm is active. Clear it first.")
        topic = f"{topics.PREFIX}/{device.node}/dose/{device.key}/command"
        await self.link.publish(topic, f"{device.dose_s:g}")
        self.conn.execute(
            "INSERT INTO dose_event (ts, device_key, seconds, source, pre_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(now), key, device.dose_s, source, pre_value),
        )
        self.conn.commit()
        self.changed = True

    def doses_since(self, key: str, since: float) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM dose_event WHERE device_key = ? AND ts > ?",
            (key, int(since)),
        ).fetchone()
        return row["n"]

    def last_dose(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT ts, pre_value, source FROM dose_event WHERE device_key = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------ leak alarm (I-10)
    def any_leak_wet(self) -> bool:
        """True if any leak sensor's last report was wet (even if its node has since died)."""
        return any((self.live.values.get(k) or {}).get("value") is True for k in self.leak_keys)

    async def _publish_leak_alarm(self) -> None:
        await self.link.publish(topics.LEAK_ALARM_TOPIC, "ON" if self.leak_alarm else "OFF", True)

    async def _set_leak_alarm(self, on: bool) -> None:
        self.leak_alarm = on
        db.set_setting(self.conn, "leak_alarm", "on" if on else "off")
        self.changed = True
        await self._publish_leak_alarm()

    async def clear_leak_alarm(self) -> None:
        """Only a person may clear the alarm, and only once every sensor is dry again."""
        if self.any_leak_wet():
            raise Refused("A leak sensor is still wet. Dry it before clearing the alarm.")
        await self._set_leak_alarm(False)

    async def on_connect(self) -> None:
        # Retained, so nodes that boot later (and a restarted broker) learn the state.
        await self._publish_leak_alarm()

    # ------------------------------------------------------------ periodic
    async def tick(self, now: float) -> None:
        if not self.leak_alarm and self.any_leak_wet():
            # Latch first, publish second: the alarm must stick even if the broker is down.
            self.leak_alarm = True
            db.set_setting(self.conn, "leak_alarm", "on")
            self.changed = True
            await self._publish_leak_alarm()
        await self._expire_overrides(now)

    @staticmethod
    def _topic(entity_key: str) -> str:
        return f"{topics.PREFIX}/{entity_key}/command"

    def snapshot(self) -> dict:
        return {"overrides": self.overrides(), "leak_alarm": self.leak_alarm}
