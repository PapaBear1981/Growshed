"""History of when each device was on: chart timelines and electricity estimates.

Only changes are stored, so this stays tiny. If a node goes offline while a device is on,
the device counts as on until the node reports again: the estimate errs on the high side.
"""

from __future__ import annotations

import sqlite3


class DeviceLog:
    def __init__(self, conn: sqlite3.Connection, keys: set[str]) -> None:
        self.conn = conn
        self.keys = keys
        self._ids: dict[str, int] = {}
        self._last: dict[str, bool] = {}
        for key in keys:
            row = conn.execute(
                "SELECT value FROM state_change WHERE series_id = ? ORDER BY ts DESC LIMIT 1",
                (self._series_id(key),),
            ).fetchone()
            if row is not None:
                self._last[key] = bool(row["value"])

    def _series_id(self, key: str) -> int:
        if key not in self._ids:
            self.conn.execute("INSERT OR IGNORE INTO series (key) VALUES (?)", (key,))
            row = self.conn.execute("SELECT id FROM series WHERE key = ?", (key,)).fetchone()
            self._ids[key] = row["id"]
        return self._ids[key]

    def record(self, key: str, on: object, ts: float) -> None:
        if key not in self.keys or not isinstance(on, bool) or self._last.get(key) == on:
            return
        self._last[key] = on
        self.conn.execute(
            "INSERT OR REPLACE INTO state_change (series_id, ts, value) VALUES (?, ?, ?)",
            (self._series_id(key), int(ts), int(on)),
        )
        self.conn.commit()

    def intervals(self, key: str, start: float, end: float) -> list[tuple[int, int]]:
        """[(on_from, on_until), ...] clipped to the range."""
        sid = self._series_id(key)
        before = self.conn.execute(
            "SELECT value FROM state_change WHERE series_id = ? AND ts <= ? "
            "ORDER BY ts DESC LIMIT 1",
            (sid, int(start)),
        ).fetchone()
        on_since = int(start) if before is not None and before["value"] else None
        out = []
        rows = self.conn.execute(
            "SELECT ts, value FROM state_change WHERE series_id = ? AND ts > ? AND ts <= ? "
            "ORDER BY ts",
            (sid, int(start), int(end)),
        )
        for row in rows:
            if row["value"] and on_since is None:
                on_since = row["ts"]
            elif not row["value"] and on_since is not None:
                out.append((on_since, row["ts"]))
                on_since = None
        if on_since is not None:
            out.append((on_since, int(end)))
        return out

    def on_seconds(self, key: str, start: float, end: float) -> int:
        return sum(b - a for a, b in self.intervals(key, start, end))


def energy(log: DeviceLog, devices, watts_of, price: float, start: float, end: float) -> dict:
    """Estimated electricity use: on-time x the wattage entered for each device."""
    rows, total_kwh = [], 0.0
    for device in devices:
        watts = watts_of(device.state_key)
        seconds = log.on_seconds(device.state_key, start, end)
        kwh = seconds * watts / 3_600_000
        total_kwh += kwh
        rows.append({"key": device.state_key, "name": device.name, "zone": device.zone,
                     "watts": watts, "hours_on": round(seconds / 3600, 1),
                     "kwh": round(kwh, 2), "cost": round(kwh * price, 2)})  # fmt: skip
    return {"devices": rows, "kwh": round(total_kwh, 2), "cost": round(total_kwh * price, 2),
            "price_per_kwh": price}  # fmt: skip
