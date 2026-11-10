"""Application factory. Run with: uvicorn growshed.main:app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router
from .config import Settings, load_config
from .ingest import Ingest
from .mqtt import run_mqtt
from .state import LiveState
from .ws import WebSocketHub


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db.connect(settings.db_path)
        db.migrate(app.state.db)
        mqtt_task = None
        if settings.mqtt_enabled:
            mqtt_task = asyncio.create_task(run_mqtt(settings, app.state.ingest))
        try:
            yield
        finally:
            if mqtt_task is not None:
                mqtt_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await mqtt_task
            app.state.db.close()

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
