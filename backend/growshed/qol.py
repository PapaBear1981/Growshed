"""API for the quality-of-life features: editable limits, crop profiles, device history and
energy, maintenance reminders, bottle levels, backups and notification preferences."""

from __future__ import annotations

import shutil
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import backup, devicelog, digest, maintenance, profiles
from .dosing import LABELS

router = APIRouter()
PUMPS = {p: LABELS[p] for p in ("ph_down", "ph_up", "nutrient_a", "nutrient_b")}


class TunableBody(BaseModel):
    key: str
    value: float


class ProfileBody(BaseModel):
    zone: str
    profile: str


class ReminderBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    every_days: int = Field(ge=1, le=365)


class BottleBody(BaseModel):
    pump: str
    capacity_ml: float = Field(gt=0, le=20000)


class PreferenceBody(BaseModel):
    key: str
    value: str


def _tunables_view(state) -> dict:
    return {
        "tunables": state.tunables.listing(),
        "profiles": sorted(profiles.PROFILES),
        "applied": profiles.current_profiles(state.tunables, state.site),
    }


def _changed(state) -> None:
    state.controller.changed = True  # the dosing and watering views show these values


# ---------------------------------------------------------------- limits and profiles
@router.get("/api/tunables")
async def get_tunables(request: Request) -> dict:
    return _tunables_view(request.app.state)


@router.put("/api/tunables")
async def set_tunable(body: TunableBody, request: Request) -> dict:
    state = request.app.state
    try:
        state.tunables.set(body.key, body.value)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _changed(state)
    return _tunables_view(state)


@router.delete("/api/tunables")
async def reset_tunable(key: str, request: Request) -> dict:
    state = request.app.state
    try:
        state.tunables.reset(key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    _changed(state)
    return _tunables_view(state)


@router.post("/api/profiles/apply")
async def apply_profile(body: ProfileBody, request: Request) -> dict:
    state = request.app.state
    try:
        profiles.apply_profile(state.tunables, state.site, body.zone, body.profile)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _changed(state)
    return _tunables_view(state)


# ---------------------------------------------------------------- device history, energy
@router.get("/api/device_history")
async def device_history(request: Request, keys: str, start: float, end: float) -> dict:
    state = request.app.state
    if not 0 < end - start <= 400 * 86400:
        raise HTTPException(422, "start must be before end, at most 400 days apart")
    wanted = [k for k in keys.split(",") if k in state.device_log.keys]
    return {k: state.device_log.intervals(k, start, end) for k in wanted}


@router.get("/api/energy")
async def get_energy(request: Request, days: float = 30) -> dict:
    state, now = request.app.state, time.time()
    if not 0 < days <= 400:
        raise HTTPException(422, "days must be between 0 and 400")
    return devicelog.energy(
        state.device_log,
        state.site.devices,
        lambda key: state.tunables.get(f"watts@{key}"),
        state.tunables.get("price_per_kwh"),
        now - days * 86400,
        now,
    )


# ---------------------------------------------------------------- maintenance
@router.get("/api/reminders")
async def get_reminders(request: Request) -> list[dict]:
    return maintenance.reminders(request.app.state.db, time.time())


@router.post("/api/reminders")
async def add_reminder(body: ReminderBody, request: Request) -> list[dict]:
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO reminder (name, every_days, last_done_at) VALUES (?, ?, ?)",
        (body.name.strip(), body.every_days, int(time.time())),
    )
    conn.commit()
    return maintenance.reminders(conn, time.time())


@router.post("/api/reminders/{reminder_id}/done")
async def reminder_done(reminder_id: int, request: Request) -> list[dict]:
    conn = request.app.state.db
    done = conn.execute(
        "UPDATE reminder SET last_done_at = ? WHERE id = ?", (int(time.time()), reminder_id)
    ).rowcount
    conn.commit()
    if not done:
        raise HTTPException(404, "no such reminder")
    return maintenance.reminders(conn, time.time())


@router.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int, request: Request) -> list[dict]:
    conn = request.app.state.db
    conn.execute("DELETE FROM reminder WHERE id = ?", (reminder_id,))
    conn.commit()
    return maintenance.reminders(conn, time.time())


@router.get("/api/bottles")
async def get_bottles(request: Request) -> list[dict]:
    return maintenance.bottles(request.app.state.db, PUMPS)


@router.post("/api/bottles")
async def refill_bottle(body: BottleBody, request: Request) -> list[dict]:
    if body.pump not in PUMPS:
        raise HTTPException(422, "unknown pump")
    conn = request.app.state.db
    maintenance.refill_bottle(conn, body.pump, body.capacity_ml, time.time())
    return maintenance.bottles(conn, PUMPS)


# ---------------------------------------------------------------- backups
def _backup_dir(state):
    return state.settings.backup_dir or state.settings.db_path.parent / "backups"


@router.get("/api/backups")
async def get_backups(request: Request) -> list[dict]:
    return backup.list_backups(_backup_dir(request.app.state))


@router.post("/api/backups/run")
async def run_backup(request: Request) -> list[dict]:
    state = request.app.state
    backup.run_backup(state.db, _backup_dir(state), state.settings.config_path, time.time())
    return backup.list_backups(_backup_dir(state))


@router.get("/api/backups/export")
async def export_backup(request: Request, tasks: BackgroundTasks) -> FileResponse:
    """Everything in one zip (database, config.yaml, photos), to keep somewhere else."""
    state = request.app.state
    photos = state.settings.db_path.parent / "photos"
    archive = backup.export_zip(state.db, state.settings.config_path, photos)
    tasks.add_task(shutil.rmtree, archive.parent, True)  # delete the temp folder afterwards
    name = time.strftime("growshed-backup-%Y%m%d.zip")
    return FileResponse(archive, media_type="application/zip", filename=name)


# ---------------------------------------------------------------- notification preferences
@router.get("/api/preferences")
async def get_preferences(request: Request) -> dict:
    return digest.preferences(request.app.state.db)


@router.put("/api/preferences")
async def set_preference(body: PreferenceBody, request: Request) -> dict:
    conn = request.app.state.db
    try:
        digest.set_preference(conn, body.key, body.value)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return digest.preferences(conn)
