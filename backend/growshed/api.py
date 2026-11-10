"""REST + WebSocket routes used by the GUI."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import db

router = APIRouter()
DEFAULT_UNITS = "imperial"


class SettingsBody(BaseModel):
    display_units: Literal["imperial", "metric"]


def _settings(request_or_ws) -> dict[str, str]:
    conn = request_or_ws.app.state.db
    return {"display_units": db.get_setting(conn, "display_units", DEFAULT_UNITS)}


@router.get("/api/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "mqtt_connected": request.app.state.live.mqtt_connected}


@router.get("/api/config")
async def get_config(request: Request) -> dict:
    return request.app.state.site.model_dump()


@router.get("/api/state")
async def get_state(request: Request) -> dict:
    return request.app.state.live.snapshot()


@router.get("/api/settings")
async def get_settings(request: Request) -> dict:
    return _settings(request)


@router.put("/api/settings")
async def put_settings(body: SettingsBody, request: Request) -> dict:
    db.set_setting(request.app.state.db, "display_units", body.display_units)
    settings = _settings(request)
    # Push to every open screen so the wall tablet follows a change made on a phone.
    await request.app.state.hub.broadcast({"type": "settings", **settings})
    return settings


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    await ws.accept()
    hub = ws.app.state.hub
    # server_time lets a screen with a wrong clock (old tablet) still judge staleness.
    await ws.send_json(
        {
            "type": "snapshot",
            **ws.app.state.live.snapshot(),
            "settings": _settings(ws),
            "server_time": time.time(),
        }
    )
    hub.add(ws)
    try:
        while True:
            await ws.receive_text()  # clients only listen; this just detects disconnects
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)
