"""REST + WebSocket routes used by the GUI."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import db, recorder
from .notify import Notification

router = APIRouter()
DEFAULT_UNITS = "imperial"


class SettingsBody(BaseModel):
    display_units: Literal["imperial", "metric"]


class CalibrationBody(BaseModel):
    key: str
    point: Literal["dry", "wet"]


FRESH_S = 180  # a calibration point must come from a reading this recent


def _settings(request_or_ws) -> dict[str, str]:
    conn = request_or_ws.app.state.db
    return {"display_units": db.get_setting(conn, "display_units", DEFAULT_UNITS)}


@router.get("/api/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "mqtt_connected": request.app.state.live.mqtt_connected}


MAX_HISTORY_SPAN_S = 400 * 86400


@router.get("/api/history")
async def get_history(
    request: Request,
    keys: str = Query(..., description="comma-separated sensor keys"),
    start: float | None = None,
    end: float | None = None,
) -> dict:
    """Averaged history for charts. Defaults to the last 24 hours."""
    end = time.time() if end is None else end
    start = end - 86400 if start is None else start
    if not 0 < end - start <= MAX_HISTORY_SPAN_S:
        raise HTTPException(422, "start must be before end, at most 400 days apart")
    wanted = [k for k in keys.split(",") if k]
    unknown = [k for k in wanted if k not in request.app.state.recorder.keys]
    if unknown or not wanted:
        raise HTTPException(422, f"not a recorded sensor: {unknown or 'none given'}")
    result = recorder.history(request.app.state.db, wanted, start, end)
    # History stores raw readings; apply today's calibration on the way out.
    cal = request.app.state.calibrations
    for key in wanted:
        if cal.needs_calibration(key):
            result["series"][key] = [cal.apply(key, v) for v in result["series"][key]]
    return result


@router.get("/api/calibration")
async def get_calibration(request: Request) -> dict:
    return request.app.state.calibrations.summary()


@router.post("/api/calibration")
async def set_calibration(body: CalibrationBody, request: Request) -> dict:
    """Store the sensor's CURRENT raw reading as its dry or wet point.

    The hub takes the reading itself (rather than trusting a number from the browser) so
    a stale screen cannot save an old value.
    """
    state = request.app.state
    cal = state.calibrations
    if not cal.needs_calibration(body.key):
        raise HTTPException(404, "that sensor does not use calibration")
    entry = state.live.values.get(body.key)
    now = time.time()
    if entry is None or entry.get("raw") is None or now - entry["ts"] > FRESH_S:
        raise HTTPException(409, "no fresh reading from that sensor; check that it is connected")
    cal.set_point(body.key, body.point, entry["raw"], now)
    await state.ingest.publish(body.key, entry["raw"], entry["ts"])  # show the new % at once
    await state.hub.broadcast({"type": "calibration", "calibration": cal.summary()})
    return cal.summary()[body.key]


@router.get("/api/alerts")
async def get_alerts(request: Request) -> dict:
    engine = request.app.state.alerts
    return {
        "active": engine.active(),
        "recent": engine.recent(),
        "notifications_configured": request.app.state.notifier.configured,
    }


@router.post("/api/alerts/{event_id}/ack")
async def ack_alert(event_id: int, request: Request) -> dict:
    engine = request.app.state.alerts
    if not engine.ack(event_id, time.time()):
        raise HTTPException(404, "no active alert with that id")
    engine.changed = False
    await request.app.state.hub.broadcast({"type": "alerts", "active": engine.active()})
    return {"ok": True}


@router.post("/api/alerts/test")
async def test_notification(request: Request) -> dict:
    """Send a test notification so phones can be set up before a real alert happens."""
    notifier = request.app.state.notifier
    if not notifier.configured:
        return {"configured": False, "sent": False}
    note = Notification("Growshed test", "Notifications are working.", 3, ("seedling",))
    return {"configured": True, "sent": await notifier.send(note)}


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
            "alerts": ws.app.state.alerts.active(),
            "calibration": ws.app.state.calibrations.summary(),
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
