"""Manual dosing log and the grow journal (plants, notes, photos).

Record-keeping only: nothing here controls anything. Photos arrive as raw image bytes
(the GUI shrinks them first), so no upload-parsing library is needed.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter()
MAX_PHOTO_BYTES = 6 * 1024 * 1024
IMAGE_TYPES = {  # leading bytes -> file extension
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
}


def image_extension(data: bytes) -> str | None:
    """Recognise an image by its content, never by the name or type the sender claims."""
    for magic, ext in IMAGE_TYPES.items():
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class DoseBody(BaseModel):
    zone: str
    product: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0, le=100000)
    unit: Literal["mL", "L", "g"] = "mL"
    note: str = Field(default="", max_length=500)
    ts: float | None = None  # defaults to now; lets a dose be logged after the fact


class PlantBody(BaseModel):
    zone: str
    name: str = Field(min_length=1, max_length=80)
    variety: str = Field(default="", max_length=80)
    started_at: float | None = None
    ended_at: float | None = None
    notes: str = Field(default="", max_length=2000)


class EntryBody(BaseModel):
    plant_id: int | None = None
    text: str = Field(default="", max_length=4000)


def _conn(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def _check_zone(request: Request, zone: str) -> None:
    if zone not in {z.id for z in request.app.state.site.zones}:
        raise HTTPException(422, f"unknown zone {zone!r}")


def _photos_dir(request: Request) -> Path:
    path = request.app.state.settings.db_path.parent / "photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- dosing log
@router.get("/api/doses")
async def list_doses(request: Request, zone: str | None = None, since: float = 0) -> list[dict]:
    sql = "SELECT * FROM dose_log WHERE ts >= ?"
    args: list = [int(since)]
    if zone:
        sql += " AND zone = ?"
        args.append(zone)
    rows = _conn(request).execute(sql + " ORDER BY ts DESC, id DESC LIMIT 500", args)
    return [dict(r) for r in rows]


@router.post("/api/doses")
async def add_dose(body: DoseBody, request: Request) -> dict:
    _check_zone(request, body.zone)
    conn = _conn(request)
    cur = conn.execute(
        "INSERT INTO dose_log (ts, zone, product, amount, unit, note) VALUES (?, ?, ?, ?, ?, ?)",
        (int(body.ts or time.time()), body.zone, body.product.strip(), body.amount, body.unit,
         body.note.strip()),
    )  # fmt: skip
    conn.commit()
    return {"id": cur.lastrowid}


@router.delete("/api/doses/{dose_id}")
async def delete_dose(dose_id: int, request: Request) -> dict:
    conn = _conn(request)
    done = conn.execute("DELETE FROM dose_log WHERE id = ?", (dose_id,)).rowcount
    conn.commit()
    if not done:
        raise HTTPException(404, "no such dose")
    return {"ok": True}


# ---------------------------------------------------------------- plants
@router.get("/api/plants")
async def list_plants(request: Request) -> list[dict]:
    rows = _conn(request).execute(
        "SELECT * FROM plant ORDER BY ended_at IS NOT NULL, started_at DESC, id DESC"
    )
    return [dict(r) for r in rows]


@router.post("/api/plants")
async def add_plant(body: PlantBody, request: Request) -> dict:
    _check_zone(request, body.zone)
    conn = _conn(request)
    cur = conn.execute(
        "INSERT INTO plant (zone, name, variety, started_at, ended_at, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.zone, body.name.strip(), body.variety.strip(), int(body.started_at or time.time()),
         int(body.ended_at) if body.ended_at else None, body.notes.strip()),
    )  # fmt: skip
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/api/plants/{plant_id}")
async def update_plant(plant_id: int, body: PlantBody, request: Request) -> dict:
    _check_zone(request, body.zone)
    conn = _conn(request)
    old = conn.execute("SELECT started_at FROM plant WHERE id = ?", (plant_id,)).fetchone()
    if old is None:
        raise HTTPException(404, "no such plant")
    conn.execute(
        "UPDATE plant SET zone = ?, name = ?, variety = ?, started_at = ?, ended_at = ?, "
        "notes = ? WHERE id = ?",
        (body.zone, body.name.strip(), body.variety.strip(),
         int(body.started_at or old["started_at"]),
         int(body.ended_at) if body.ended_at else None, body.notes.strip(), plant_id),
    )  # fmt: skip
    conn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- journal entries
@router.get("/api/journal")
async def list_entries(request: Request, plant_id: int | None = None) -> list[dict]:
    sql, args = "SELECT * FROM journal_entry", []
    if plant_id is not None:
        sql += " WHERE plant_id = ?"
        args.append(plant_id)
    rows = _conn(request).execute(sql + " ORDER BY ts DESC, id DESC LIMIT 300", args)
    return [dict(r) for r in rows]


@router.post("/api/journal")
async def add_entry(body: EntryBody, request: Request) -> dict:
    conn = _conn(request)
    if body.plant_id is not None:
        if conn.execute("SELECT 1 FROM plant WHERE id = ?", (body.plant_id,)).fetchone() is None:
            raise HTTPException(422, "no such plant")
    cur = conn.execute(
        "INSERT INTO journal_entry (ts, plant_id, text) VALUES (?, ?, ?)",
        (int(time.time()), body.plant_id, body.text.strip()),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/api/journal/{entry_id}/photo")
async def set_photo(entry_id: int, request: Request) -> dict:
    """Attach a photo: the request body is the image itself (JPEG, PNG or WebP)."""
    conn = _conn(request)
    row = conn.execute("SELECT photo FROM journal_entry WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such entry")
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo too large")
    data = await request.body()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo too large")
    ext = image_extension(data)
    if ext is None:
        raise HTTPException(415, "not a JPEG, PNG or WebP image")
    folder = _photos_dir(request)
    name = f"{entry_id}-{secrets.token_hex(8)}.{ext}"  # we choose the name, never the sender
    (folder / name).write_bytes(data)
    if row["photo"]:
        (folder / row["photo"]).unlink(missing_ok=True)
    conn.execute("UPDATE journal_entry SET photo = ? WHERE id = ?", (name, entry_id))
    conn.commit()
    return {"photo": name}


@router.delete("/api/journal/{entry_id}")
async def delete_entry(entry_id: int, request: Request) -> dict:
    conn = _conn(request)
    row = conn.execute("SELECT photo FROM journal_entry WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such entry")
    if row["photo"]:
        (_photos_dir(request) / row["photo"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM journal_entry WHERE id = ?", (entry_id,))
    conn.commit()
    return {"ok": True}


@router.get("/api/photos/{name}")
async def get_photo(name: str, request: Request) -> FileResponse:
    # Only names we generated ourselves are ever stored, and only those are served.
    known = (
        _conn(request).execute("SELECT 1 FROM journal_entry WHERE photo = ?", (name,)).fetchone()
    )
    path = _photos_dir(request) / name
    if known is None or not path.is_file():
        raise HTTPException(404, "no such photo")
    return FileResponse(path)
