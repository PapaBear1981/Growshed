"""The hub's periodic jobs: alert evaluation, notification delivery, history upkeep."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import FastAPI

from . import backup, db
from .digest import build_summary
from .mqtt import NotConnected
from .notify import Notification, Notifier, ping

log = logging.getLogger(__name__)

TICK_S = 2
FLUSH_EVERY_S = 10
ROLLUP_EVERY_S = 300
PRUNE_EVERY_S = 3600
PING_EVERY_S = 300
WATERING_EVERY_S = 30
DOSING_EVERY_S = 5
SUMMARY_CHECK_S = 60
BACKUP_CHECK_S = 600
BACKUP_EVERY_S = 86400
RETRY_DELAY_S = 30
GIVE_UP_AFTER_S = 900


def control_view(state, now: float) -> dict:
    """Everything the Controls page needs that is not already in the live values."""
    return {
        **state.controller.snapshot(),
        "watering": state.watering.status(now),
        "dosing": state.dosing.snapshot(now) if state.dosing is not None else None,
    }


def nightly_backup(state, now: float) -> None:
    """Snapshot the database and config once a day."""
    if now - float(db.get_setting(state.db, "backup_last", "0")) < BACKUP_EVERY_S:
        return
    folder = state.settings.backup_dir or state.settings.db_path.parent / "backups"
    backup.run_backup(state.db, folder, state.settings.config_path, now)
    db.set_setting(state.db, "backup_last", str(int(now)))


async def deliver(notifier: Notifier, queue: asyncio.Queue[Notification]) -> None:
    """Send notifications one at a time, retrying through short internet outages.

    Runs separately from the alert loop so a slow ntfy server cannot delay alert
    evaluation or the dashboard.
    """
    while True:
        note = await queue.get()
        first_try = time.monotonic()
        while not await notifier.send(note):
            if time.monotonic() - first_try > GIVE_UP_AFTER_S:
                log.error("gave up sending notification: %s", note.title)
                break
            await asyncio.sleep(RETRY_DELAY_S)


async def run_background(app: FastAPI) -> None:
    state = app.state
    queue: asyncio.Queue[Notification] = asyncio.Queue()
    sender = asyncio.create_task(deliver(state.notifier, queue))
    jobs = ("flush", "rollup", "prune", "ping", "watering", "dosing", "summary", "backup")
    last = dict.fromkeys(jobs, 0.0)

    def due(job: str, every_s: float, now: float) -> bool:
        if now - last[job] >= every_s:
            last[job] = now
            return True
        return False

    try:
        while True:
            now = time.time()
            try:
                try:
                    await state.controller.tick(now)
                    if due("watering", WATERING_EVERY_S, now):
                        await state.watering.tick(now)
                    if state.dosing is not None and due("dosing", DOSING_EVERY_S, now):
                        await state.dosing.tick(now)
                except NotConnected:
                    pass  # broker down: nodes are in fallback anyway; retry next tick
                if state.controller.changed:
                    state.controller.changed = False
                    await state.hub.broadcast({"type": "control", **control_view(state, now)})
                # Quiet hours: warnings wait for morning, critical alerts never do.
                for note in state.alerts.tick(now):
                    for out in state.courier.route(note, now):
                        queue.put_nowait(out)
                for out in state.courier.release(now):
                    queue.put_nowait(out)
                if due("summary", SUMMARY_CHECK_S, now) and state.courier.summary_due(now):
                    queue.put_nowait(build_summary(state, now))
                if due("backup", BACKUP_CHECK_S, now):
                    nightly_backup(state, now)
                if state.alerts.changed:
                    state.alerts.changed = False
                    await state.hub.broadcast({"type": "alerts", "active": state.alerts.active()})
                if due("flush", FLUSH_EVERY_S, now):
                    state.recorder.flush()
                if due("rollup", ROLLUP_EVERY_S, now):
                    state.recorder.rollup(now)
                if due("prune", PRUNE_EVERY_S, now):
                    state.recorder.prune(now)
                if state.settings.healthcheck_url and due("ping", PING_EVERY_S, now):
                    # Fire-and-forget; keep a reference so the task is not garbage collected.
                    state.ping_task = asyncio.create_task(ping(state.settings.healthcheck_url))
            except Exception:
                # A bug in one job must not stop alerts for the rest of the night.
                log.exception("background job failed")
            await asyncio.sleep(TICK_S)
    finally:
        sender.cancel()
        state.recorder.flush()
