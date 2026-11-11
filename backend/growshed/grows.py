"""Grow history: one record per grow, kept forever, so past grows can be looked back on
and compared. Statistics come from the same database as everything else (hourly sensor
summaries are never deleted), and are frozen into the record when a grow ends."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import devicelog, recorder

router = APIRouter()


class GrowBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    zone: str
    crop: str = Field(default="", max_length=80)
    started_at: float | None = None
    notes: str = Field(default="", max_length=4000)
    yield_g: float | None = Field(default=None, ge=0, le=1_000_000)


class GrowEndBody(BaseModel):
    action: Literal["end", "reopen"]
    yield_g: float | None = Field(default=None, ge=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=4000)


def summarize(state, grow: sqlite3.Row, now: float) -> dict:
    """Everything worth knowing about one grow's period, in SI units."""
    conn, site, cal = state.db, state.site, state.calibrations
    start, end = grow["started_at"], grow["ended_at"] or now
    family = [grow["zone"]] + [z.id for z in site.zones if z.parent == grow["zone"]]
    # A tent's plants also depend on the reservoirs: include every reservoir zone too.
    related = family + [z.id for z in site.zones if z.kind == "rdwc" and z.id not in family]
    zones = {z.id: z.name for z in site.zones}

    sensors = []
    for sensor in site.sensors:
        if sensor.component != "sensor" or sensor.zone not in related:
            continue
        s = recorder.stats(conn, sensor.state_key, start, end)
        if s is None:
            continue
        # Calibration may run high-to-low (pH, soil), so order the extremes after applying it.
        ends = [cal.apply(sensor.state_key, s["min"]), cal.apply(sensor.state_key, s["max"])]
        ends = [v for v in ends if v is not None]
        avg = cal.apply(sensor.state_key, s["avg"])
        if not ends or avg is None:
            continue
        sensors.append(
            {
                "key": sensor.state_key,
                "name": f"{zones[sensor.zone]} · {sensor.name}",
                "kind": sensor.kind,
                "min": min(ends),
                "avg": avg,
                "max": max(ends),
            }
        )

    def count(sql: str, *args) -> int:
        return conn.execute(sql, args).fetchone()[0]

    names = [zones[z] for z in family]
    alerts = sum(
        count("SELECT COUNT(*) FROM alert_event WHERE started_at BETWEEN ? AND ? "
              "AND subject LIKE ?", int(start), int(end), name + "%")
        for name in names
    )  # fmt: skip
    price = state.tunables.get("price_per_kwh")
    power = devicelog.energy(
        state.device_log, [d for d in site.devices if d.zone in family],
        lambda key: state.tunables.get(f"watts@{key}"), price, start, end,
    )  # fmt: skip
    plants = [dict(r) for r in conn.execute(
        "SELECT id, name, variety FROM plant WHERE grow_id = ?", (grow["id"],))]  # fmt: skip
    additions = [
        dict(r)
        for r in conn.execute(
            "SELECT product, unit, ROUND(SUM(amount), 1) AS total, COUNT(*) AS times "
            "FROM dose_log WHERE ts BETWEEN ? AND ? GROUP BY product, unit ORDER BY product",
            (int(start), int(end)),
        )
    ]
    return {
        "days": max(1, round((end - start) / 86400)),
        "sensors": sensors,
        "alerts": alerts,
        "additions": additions,
        "waterings": count("SELECT COUNT(*) FROM dose_event WHERE ts BETWEEN ? AND ?",
                           int(start), int(end)),
        "energy_kwh": power["kwh"],
        "energy_cost": power["cost"],
        "plants": plants,
        "journal_entries": count(
            "SELECT COUNT(*) FROM journal_entry WHERE ts BETWEEN ? AND ? AND "
            "(plant_id IS NULL OR plant_id IN (SELECT id FROM plant WHERE grow_id = ?))",
            int(start), int(end), grow["id"]),
    }  # fmt: skip


def _view(state, grow: sqlite3.Row, now: float, with_summary: bool) -> dict:
    out = {k: grow[k] for k in ("id", "name", "zone", "crop", "started_at", "ended_at", "notes",
                                "yield_g")}  # fmt: skip
    if grow["ended_at"] and grow["summary"]:
        out["summary"] = json.loads(grow["summary"])  # frozen when the grow ended
    elif with_summary:
        out["summary"] = summarize(state, grow, now)
    return out


def _get(request: Request, grow_id: int) -> sqlite3.Row:
    row = request.app.state.db.execute("SELECT * FROM grow WHERE id = ?", (grow_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such grow")
    return row


def _check_zone(request: Request, zone: str) -> None:
    if zone not in {z.id for z in request.app.state.site.zones}:
        raise HTTPException(422, f"unknown zone {zone!r}")


@router.get("/api/grows")
async def list_grows(request: Request) -> list[dict]:
    state, now = request.app.state, time.time()
    rows = state.db.execute(
        "SELECT * FROM grow ORDER BY ended_at IS NOT NULL, started_at DESC, id DESC"
    ).fetchall()
    return [_view(state, row, now, with_summary=False) for row in rows]


@router.get("/api/grows/{grow_id}")
async def get_grow(grow_id: int, request: Request) -> dict:
    return _view(request.app.state, _get(request, grow_id), time.time(), with_summary=True)


@router.post("/api/grows")
async def add_grow(body: GrowBody, request: Request) -> dict:
    _check_zone(request, body.zone)
    conn = request.app.state.db
    cur = conn.execute(
        "INSERT INTO grow (name, zone, crop, started_at, notes) VALUES (?, ?, ?, ?, ?)",
        (body.name.strip(), body.zone, body.crop.strip(), int(body.started_at or time.time()),
         body.notes.strip()),
    )  # fmt: skip
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/api/grows/{grow_id}")
async def update_grow(grow_id: int, body: GrowBody, request: Request) -> dict:
    old = _get(request, grow_id)
    _check_zone(request, body.zone)
    conn = request.app.state.db
    conn.execute(
        "UPDATE grow SET name = ?, zone = ?, crop = ?, started_at = ?, notes = ?, yield_g = ? "
        "WHERE id = ?",
        (body.name.strip(), body.zone, body.crop.strip(),
         int(body.started_at or old["started_at"]), body.notes.strip(), body.yield_g, grow_id),
    )  # fmt: skip
    conn.commit()
    return {"ok": True}


@router.post("/api/grows/{grow_id}/status")
async def end_or_reopen(grow_id: int, body: GrowEndBody, request: Request) -> dict:
    state, now = request.app.state, time.time()
    grow = _get(request, grow_id)
    conn = state.db
    if body.action == "reopen":
        conn.execute("UPDATE grow SET ended_at = NULL, summary = NULL WHERE id = ?", (grow_id,))
    else:
        if body.yield_g is not None or body.notes is not None:
            conn.execute(
                "UPDATE grow SET yield_g = COALESCE(?, yield_g), notes = COALESCE(?, notes) "
                "WHERE id = ?",
                (body.yield_g, body.notes, grow_id),
            )
        # Freeze the statistics now, so the record never changes after the grow is over.
        summary = summarize(state, grow, now)
        conn.execute(
            "UPDATE grow SET ended_at = ?, summary = ? WHERE id = ?",
            (int(now), json.dumps(summary), grow_id),
        )
        conn.execute(
            "UPDATE plant SET ended_at = ? WHERE grow_id = ? AND ended_at IS NULL",
            (int(now), grow_id),
        )
    conn.commit()
    return _view(state, _get(request, grow_id), now, with_summary=True)
