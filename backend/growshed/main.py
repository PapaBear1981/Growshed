"""Application factory. Run with: uvicorn growshed.main:app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .alerts import AlertEngine, Condition
from .api import router
from .background import run_background
from .calibration import MAX_AGE_DAYS, Calibrations
from .config import Settings, load_config
from .control import Controller
from .ingest import Ingest
from .mqtt import MqttLink, run_mqtt
from .notify import Notifier
from .recorder import Recorder
from .state import LiveState
from .watering import Watering
from .ws import WebSocketHub


def _water_temp_lookup(site, live: LiveState):
    """EC needs its reservoir's temperature: the temperature sensor in the same zone."""
    partner = {}
    for sensor in site.sensors:
        if sensor.kind == "ec":
            temp = next(
                (t for t in site.sensors if t.zone == sensor.zone and t.kind == "temperature"), None
            )
            if temp is not None:
                partner[sensor.state_key] = temp.state_key

    def lookup(key: str) -> float | None:
        entry = live.values.get(partner.get(key, ""))
        if entry is None or entry["value"] is None or time.time() - entry["ts"] > 600:
            return None
        return entry["value"]

    return lookup


def _calibration_conditions(cal: Calibrations, site) -> list[Condition]:
    """Cheap pH and EC probes drift: remind the owner when a calibration is due."""
    names = {s.state_key: s for s in site.sensors}
    zones = {z.id: z.name for z in site.zones}
    out = []
    for key, kind in cal.kinds.items():
        limit = MAX_AGE_DAYS.get(kind)
        if limit is None:
            continue

        def due(now: float, k: str = key, days: int = limit) -> tuple[bool | None, str]:
            age = cal.age_days(k, now)
            if age is None:
                return None, ""
            return age > days, f"last calibrated {age:.0f} days ago"

        sensor = names[key]
        out.append(
            Condition(
                f"calibration_due:{key}",
                "Calibration is due",
                f"{zones[sensor.zone]} · {sensor.name}",
                "warning",
                0,
                None,
                due,
            )
        )
    return out


def _control_conditions(controller: Controller, watering: Watering) -> list[Condition]:
    """Alerts about the control layer itself: the leak latch and stopped auto-watering."""
    out = [
        Condition(
            "leak_alarm",
            "Leak alarm: pumps are stopped",
            "All water pumps stay off until the alarm is cleared on the Controls page",
            "critical",
            0,
            None,
            lambda now: (controller.leak_alarm, ""),
        )
    ]
    for key, pot in watering.pots.items():

        def locked(now: float, k: str = key) -> tuple[bool, str]:
            reason = watering.locked_reason(k)
            return reason is not None, reason or ""

        out.append(
            Condition(
                f"watering_locked:{key}",
                "Auto-watering stopped",
                pot.name,
                "warning",
                0,
                None,
                locked,
            )
        )
    return out


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = app.state.db = db.connect(settings.db_path)
        db.migrate(conn)
        site = app.state.site
        recorded = {s.state_key for s in site.sensors if s.component == "sensor"}
        app.state.recorder = Recorder(conn, recorded)
        app.state.ingest.recorder = app.state.recorder
        app.state.calibrations = Calibrations(
            conn,
            {s.state_key: s.kind for s in site.sensors if s.component == "sensor"},
            _water_temp_lookup(site, app.state.live),
        )
        app.state.ingest.calibrations = app.state.calibrations
        app.state.notifier = Notifier(settings.ntfy_url, settings.ntfy_token)
        link = app.state.link = MqttLink()
        controller = app.state.controller = Controller(conn, site, app.state.live, link)
        link.on_connect = controller.on_connect
        watering = app.state.watering = Watering(
            conn, site, app.state.live, app.state.calibrations, controller
        )
        app.state.alerts = AlertEngine(
            conn,
            site,
            app.state.live,
            started_at=time.time(),
            get_units=lambda: db.get_setting(conn, "display_units", "imperial"),
            extra=[
                *_control_conditions(controller, watering),
                *_calibration_conditions(app.state.calibrations, site),
            ],
        )
        tasks = []
        if settings.mqtt_enabled:
            tasks.append(asyncio.create_task(run_mqtt(settings, app.state.ingest, link)))
        if settings.background_enabled:
            tasks.append(asyncio.create_task(run_background(app)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            conn.close()

    app = FastAPI(title="Growshed", lifespan=lifespan)
    app.state.settings = settings
    app.state.site = load_config(settings.config_path)  # fail fast on a bad config.yaml
    app.state.live = LiveState()
    app.state.hub = WebSocketHub()
    app.state.ingest = Ingest(app.state.live, app.state.hub)
    app.include_router(router)
    if settings.static_dir.is_dir():
        # Built frontend. Mounted last so /api and /ws take priority.
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
    return app


def app() -> FastAPI:  # uvicorn entry point: `uvicorn growshed.main:app --factory`
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
