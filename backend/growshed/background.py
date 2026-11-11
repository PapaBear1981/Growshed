"""The hub's periodic jobs: alert evaluation, notification delivery, history upkeep."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import FastAPI

from .notify import Notification, Notifier, ping

log = logging.getLogger(__name__)

TICK_S = 2
FLUSH_EVERY_S = 10
ROLLUP_EVERY_S = 300
PRUNE_EVERY_S = 3600
PING_EVERY_S = 300
RETRY_DELAY_S = 30
GIVE_UP_AFTER_S = 900


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
    last = {"flush": 0.0, "rollup": 0.0, "prune": 0.0, "ping": 0.0}

    def due(job: str, every_s: float, now: float) -> bool:
        if now - last[job] >= every_s:
            last[job] = now
            return True
        return False

    try:
        while True:
            now = time.time()
            try:
                for note in state.alerts.tick(now):
                    queue.put_nowait(note)
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
