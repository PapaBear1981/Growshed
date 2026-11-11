"""Stores sensor history and serves it back for charts.

Three resolutions keep the database small on the Pi's SSD: raw readings for 30 days,
5-minute summaries for a year, hourly summaries forever.
"""

from __future__ import annotations

import sqlite3

from . import db

RAW_KEEP_S = 30 * 86400
FIVE_MIN_KEEP_S = 365 * 86400
ROLLUP_LAG_S = 60  # leave the newest minute alone so buffered readings are not missed


class Recorder:
    def __init__(self, conn: sqlite3.Connection, keys: set[str], min_interval_s: float = 15):
        self.conn = conn
        self.keys = keys  # only configured numeric sensors are stored
        self.min_interval_s = min_interval_s
        self._last_ts: dict[str, int] = {}
        self._buffer: list[tuple[str, int, float]] = []
        self._ids: dict[str, int] = {}

    def add(self, key: str, value: object, ts: float) -> None:
        """Queue one reading. Cheap enough to call for every MQTT message."""
        if key not in self.keys or isinstance(value, bool) or not isinstance(value, int | float):
            return
        t = int(ts)
        # Throttle chatty sources (the simulator publishes every few seconds).
        if t - self._last_ts.get(key, 0) < self.min_interval_s:
            return
        self._last_ts[key] = t
        self._buffer.append((key, t, float(value)))

    def _series_id(self, key: str) -> int:
        if key not in self._ids:
            self.conn.execute("INSERT OR IGNORE INTO series (key) VALUES (?)", (key,))
            row = self.conn.execute("SELECT id FROM series WHERE key = ?", (key,)).fetchone()
            self._ids[key] = row["id"]
        return self._ids[key]

    def flush(self) -> int:
        """Write queued readings in one transaction. Returns how many were written."""
        if not self._buffer:
            return 0
        rows = [(self._series_id(key), t, value) for key, t, value in self._buffer]
        self._buffer.clear()
        self.conn.executemany(
            "INSERT OR REPLACE INTO reading (series_id, ts, value) VALUES (?, ?, ?)", rows
        )
        self.conn.commit()
        return len(rows)

    def rollup(self, now: float) -> None:
        """Summarise finished 5-minute and 1-hour buckets. Safe to call as often as you like."""
        conn = self.conn
        done = int(db.get_setting(conn, "rollup_5m_until", "0"))
        end = int(now - ROLLUP_LAG_S) // 300 * 300
        if end > done:
            conn.execute(
                "INSERT OR REPLACE INTO reading_5m (series_id, ts, min, max, avg, n) "
                "SELECT series_id, ts / 300 * 300, MIN(value), MAX(value), AVG(value), COUNT(*) "
                "FROM reading WHERE ts >= ? AND ts < ? GROUP BY 1, 2",
                (done, end),
            )
            db.set_setting(conn, "rollup_5m_until", str(end))

        done = int(db.get_setting(conn, "rollup_1h_until", "0"))
        end = int(db.get_setting(conn, "rollup_5m_until", "0")) // 3600 * 3600
        if end > done:
            conn.execute(
                "INSERT OR REPLACE INTO reading_1h (series_id, ts, min, max, avg, n) "
                "SELECT series_id, ts / 3600 * 3600, MIN(min), MAX(max), "
                "SUM(avg * n) / SUM(n), SUM(n) "
                "FROM reading_5m WHERE ts >= ? AND ts < ? GROUP BY 1, 2",
                (done, end),
            )
            db.set_setting(conn, "rollup_1h_until", str(end))

    def prune(self, now: float) -> None:
        """Delete data past its retention. Only data that has already been summarised."""
        conn = self.conn
        raw_cut = min(int(now) - RAW_KEEP_S, int(db.get_setting(conn, "rollup_5m_until", "0")))
        five_cut = min(
            int(now) - FIVE_MIN_KEEP_S, int(db.get_setting(conn, "rollup_1h_until", "0"))
        )
        conn.execute("DELETE FROM reading WHERE ts < ?", (raw_cut,))
        conn.execute("DELETE FROM reading_5m WHERE ts < ?", (five_cut,))
        conn.commit()


def bucket_for_span(span_s: float) -> int:
    """Chart resolution: fine for short ranges, coarse for long ones (keeps charts fast)."""
    if span_s <= 12 * 3600:
        return 60
    if span_s <= 10 * 86400:
        return 300
    return 3600


def history(conn: sqlite3.Connection, keys: list[str], start: float, end: float) -> dict:
    """Averaged readings on one shared time grid: {"bucket_s", "t": [...], "series": {key: [...]}}.

    Every series is aligned to the same timestamps (None where there is no data), which
    is the shape the chart library needs.
    """
    bucket = bucket_for_span(end - start)
    first = int(start) // bucket * bucket
    grid = list(range(first, int(end) + 1, bucket))
    index = {t: i for i, t in enumerate(grid)}
    series: dict[str, list[float | None]] = {key: [None] * len(grid) for key in keys}

    ids = {}
    for key in keys:
        row = conn.execute("SELECT id FROM series WHERE key = ?", (key,)).fetchone()
        if row:
            ids[row["id"]] = key
    if not ids:
        return {"bucket_s": bucket, "t": grid, "series": series}
    marks = ",".join("?" * len(ids))
    id_args = list(ids)
    lo, hi = first, int(end)

    def fill(rows) -> None:
        for row in rows:
            i = index.get(row["t"])
            if i is not None:
                series[ids[row["series_id"]]][i] = row["v"]

    raw_sql = (
        f"SELECT series_id, ts / {bucket} * {bucket} AS t, AVG(value) AS v FROM reading "
        f"WHERE series_id IN ({marks}) AND ts >= ? AND ts <= ? GROUP BY 1, 2"
    )
    if bucket == 60:
        fill(conn.execute(raw_sql, [*id_args, lo, hi]))
    elif bucket == 300:
        done = int(db.get_setting(conn, "rollup_5m_until", "0"))
        fill(
            conn.execute(
                f"SELECT series_id, ts AS t, avg AS v FROM reading_5m "
                f"WHERE series_id IN ({marks}) AND ts >= ? AND ts <= ? AND ts < ?",
                [*id_args, lo, hi, done],
            )
        )
        # The newest few minutes are not summarised yet: take them from the raw table.
        fill(conn.execute(raw_sql, [*id_args, max(lo, done), hi]))
    else:
        done = int(db.get_setting(conn, "rollup_1h_until", "0"))
        fill(
            conn.execute(
                f"SELECT series_id, ts AS t, avg AS v FROM reading_1h "
                f"WHERE series_id IN ({marks}) AND ts >= ? AND ts <= ? AND ts < ?",
                [*id_args, lo, hi, done],
            )
        )
        fill(
            conn.execute(
                f"SELECT series_id, ts / 3600 * 3600 AS t, SUM(avg * n) / SUM(n) AS v "
                f"FROM reading_5m WHERE series_id IN ({marks}) AND ts >= ? AND ts <= ? "
                f"GROUP BY 1, 2",
                [*id_args, max(lo, done), hi],
            )
        )
    return {"bucket_s": bucket, "t": grid, "series": series}
