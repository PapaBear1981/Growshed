"""Daily summary and quiet hours for phone notifications.

Quiet hours hold back warnings overnight and deliver them as one message in the morning.
CRITICAL alerts (leaks, low reservoirs) are never held: they always go out at once.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db, maintenance, recorder
from .notify import Notification
from .units import format_value

SUMMARY_KINDS = ("temperature", "humidity", "ph", "ec")
DEFAULTS = {
    "timezone": "UTC",
    "summary_enabled": "1",
    "summary_minute": "480",  # 08:00
    "quiet_enabled": "0",
    "quiet_start": "1320",  # 22:00
    "quiet_end": "420",  # 07:00
}


def preferences(conn: sqlite3.Connection) -> dict[str, str]:
    return {key: db.get_setting(conn, "pref:" + key, default) for key, default in DEFAULTS.items()}


def set_preference(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Validate and store one preference. Raises ValueError with a message for the user."""
    if key not in DEFAULTS:
        raise ValueError("Unknown preference.")
    if key == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone {value!r}.") from exc
    elif key.endswith("_enabled"):
        if value not in ("0", "1"):
            raise ValueError("Must be on or off.")
    elif not (value.isdigit() and 0 <= int(value) < 1440):
        raise ValueError("Times are minutes after midnight (0 to 1439).")
    db.set_setting(conn, "pref:" + key, value)


def local_time(prefs: dict[str, str], now: float) -> datetime:
    try:
        zone = ZoneInfo(prefs["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.fromtimestamp(now, zone)


def in_quiet_hours(prefs: dict[str, str], now: float) -> bool:
    if prefs["quiet_enabled"] != "1":
        return False
    local = local_time(prefs, now)
    minute = local.hour * 60 + local.minute
    start, end = int(prefs["quiet_start"]), int(prefs["quiet_end"])
    if start == end:
        return False
    return start <= minute < end if start < end else (minute >= start or minute < end)


class Courier:
    """Decides, for each notification, whether it goes out now or waits for morning."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.held: list[Notification] = []

    def route(self, note: Notification, now: float) -> list[Notification]:
        if note.priority < 5 and in_quiet_hours(preferences(self.conn), now):
            self.held.append(note)
            return []
        return [note]

    def release(self, now: float) -> list[Notification]:
        """Once quiet hours are over, everything held becomes one message."""
        if not self.held or in_quiet_hours(preferences(self.conn), now):
            return []
        lines = [f"{n.title}: {n.body}" for n in self.held]
        count = len(self.held)
        self.held = []
        title = f"{count} alert{'s' if count != 1 else ''} during quiet hours"
        return [Notification(title, "\n".join(lines[:15]), 3, ("zzz",))]

    def summary_due(self, now: float) -> bool:
        """True once per day, at or after the chosen local time."""
        prefs = preferences(self.conn)
        if prefs["summary_enabled"] != "1":
            return False
        local = local_time(prefs, now)
        today = local.strftime("%Y-%m-%d")
        if db.get_setting(self.conn, "summary_sent", "") == today:
            return False
        if local.hour * 60 + local.minute < int(prefs["summary_minute"]):
            return False
        db.set_setting(self.conn, "summary_sent", today)
        return True


def build_summary(state, now: float) -> Notification:
    """One morning message: the last 24 hours in a few lines."""
    conn, site, cal = state.db, state.site, state.calibrations
    units = db.get_setting(conn, "display_units", "imperial")
    zones = {z.id: z.name for z in site.zones}
    lines = []
    for sensor in site.sensors:
        if sensor.component != "sensor" or sensor.kind not in SUMMARY_KINDS:
            continue
        s = recorder.stats(conn, sensor.state_key, now - 86400, now)
        if s is None:
            continue
        # Calibration may run high-to-low (pH), so order the extremes after applying it.
        ends = [cal.apply(sensor.state_key, s["min"]), cal.apply(sensor.state_key, s["max"])]
        ends = sorted(v for v in ends if v is not None)
        if not ends:
            continue
        low = format_value(sensor.kind, ends[0], units)
        high = format_value(sensor.kind, ends[-1], units)
        lines.append(f"{zones[sensor.zone]} {sensor.name.lower()}: {low} to {high}")
    active = state.alerts.active()
    lines.append(f"Active alerts: {len(active)}" + (f" ({active[0]['name']})" if active else ""))
    due = maintenance.overdue(conn, now)
    if due:
        lines.append("Maintenance due: " + "; ".join(due[:4]))
    doses = conn.execute(
        "SELECT COUNT(*) AS n FROM dose_log WHERE ts > ?", (int(now - 86400),)
    ).fetchone()["n"]
    if doses:
        lines.append(f"Additions logged: {doses}")
    day = time.strftime("%a %d %b", local_time(preferences(conn), now).timetuple())
    return Notification(f"Growshed daily summary, {day}", "\n".join(lines), 2, ("seedling",))
