"""Maintenance reminders and dosing-bottle levels. Record-keeping only: nothing here
controls anything."""

from __future__ import annotations

import sqlite3

DAY_S = 86400
LOW_BOTTLE_FRACTION = 0.15


def reminders(conn: sqlite3.Connection, now: float) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM reminder ORDER BY name"):
        due_at = row["last_done_at"] + row["every_days"] * DAY_S
        out.append({**dict(row), "due_at": due_at, "overdue": now >= due_at,
                    "days_left": int((due_at - now) // DAY_S)})  # fmt: skip
    return sorted(out, key=lambda r: r["due_at"])


def overdue(conn: sqlite3.Connection, now: float) -> list[str]:
    return [r["name"] for r in reminders(conn, now) if r["overdue"]]


def bottles(conn: sqlite3.Connection, pumps: dict[str, str]) -> list[dict]:
    """What is left in each chemical bottle: capacity minus everything dosed since refill.

    An estimate. Priming and calibration runs are not counted, so check the real bottle
    when the level gets low.
    """
    stored = {row["pump"]: row for row in conn.execute("SELECT * FROM bottle")}
    out = []
    for pump, label in pumps.items():
        row = stored.get(pump)
        if row is None:
            out.append({"pump": pump, "label": label, "capacity_ml": None, "left_ml": None,
                        "low": False})  # fmt: skip
            continue
        used = conn.execute(
            "SELECT COALESCE(SUM(ml), 0) AS total FROM chem_dose WHERE pump = ? AND ts >= ?",
            (pump, row["filled_at"]),
        ).fetchone()["total"]
        left = max(0.0, row["capacity_ml"] - used)
        out.append({"pump": pump, "label": label, "capacity_ml": row["capacity_ml"],
                    "left_ml": round(left, 1), "filled_at": row["filled_at"],
                    "low": left <= row["capacity_ml"] * LOW_BOTTLE_FRACTION})  # fmt: skip
    return out


def refill_bottle(conn: sqlite3.Connection, pump: str, capacity_ml: float, now: float) -> None:
    conn.execute(
        "INSERT INTO bottle (pump, capacity_ml, filled_at) VALUES (?, ?, ?) "
        "ON CONFLICT(pump) DO UPDATE SET capacity_ml = excluded.capacity_ml, "
        "filled_at = excluded.filled_at",
        (pump, capacity_ml, int(now)),
    )
    conn.commit()
