"""REST + WebSocket routes used by the GUI."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import db, recorder
from .background import control_view
from .control import Refused
from .mqtt import NotConnected
from .notify import Notification

router = APIRouter()
DEFAULT_UNITS = "imperial"


class SettingsBody(BaseModel):
    display_units: Literal["imperial", "metric"]


class ModeBody(BaseModel):
    key: str
    mode: Literal["auto", "on", "off"]
    hours: float | None = None  # how long a manual on/off lasts; None = until changed


class NumberBody(BaseModel):
    key: str
    value: float


class KeyBody(BaseModel):
    key: str


class PotModeBody(BaseModel):
    key: str
    mode: Literal["off", "auto"]


class CalibrationBody(BaseModel):
    key: str
    label: Literal["dry", "wet", "ph", "ec", "offset"]
    ref: float | None = None  # buffer pH, solution EC (µS/cm) or the reference reading


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
        if cal.uses(key):
            result["series"][key] = [cal.apply(key, v) for v in result["series"][key]]
    return result


@router.get("/api/calibration")
async def get_calibration(request: Request) -> dict:
    return request.app.state.calibrations.summary()


@router.post("/api/calibration")
async def set_calibration(body: CalibrationBody, request: Request) -> dict:
    """Capture a calibration point from the sensor's own recent readings.

    The hub takes the reading itself (rather than trusting a number from the browser)
    and only once it is steady. While it is not, the answer is {"status": "waiting"} and
    the GUI asks again.
    """
    state = request.app.state
    cal = state.calibrations
    if not cal.uses(body.key):
        raise HTTPException(404, "that sensor does not use calibration")
    try:
        result = cal.capture(body.key, body.label, body.ref, time.time())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result["status"] == "saved":
        await _refresh_calibrated(state, body.key)
    return result


@router.delete("/api/calibration")
async def clear_calibration(key: str, request: Request) -> dict:
    state = request.app.state
    if not state.calibrations.uses(key):
        raise HTTPException(404, "that sensor does not use calibration")
    state.calibrations.clear(key)
    await _refresh_calibrated(state, key)
    return {"status": "cleared"}


async def _refresh_calibrated(state, key: str) -> None:
    """After a calibration change, show the new value at once on every screen."""
    entry = state.live.values.get(key)
    if entry is not None and entry.get("raw") is not None:
        await state.ingest.publish(key, entry["raw"], entry["ts"])
    await state.hub.broadcast({"type": "calibration", "calibration": state.calibrations.summary()})


async def _control(request: Request, action) -> dict:
    """Run a control action, turning its refusals into answers the GUI can show."""
    state = request.app.state
    try:
        await action(state, time.time())
    except Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    except NotConnected as exc:
        raise HTTPException(503, "The hub is not connected to the nodes right now.") from exc
    state.controller.changed = False
    view = control_view(state, time.time())
    await state.hub.broadcast({"type": "control", **view})
    return view


@router.get("/api/control")
async def get_control(request: Request) -> dict:
    return control_view(request.app.state, time.time())


@router.post("/api/control/mode")
async def set_mode(body: ModeBody, request: Request) -> dict:
    if body.hours is not None and not 0 < body.hours <= 72:
        raise HTTPException(422, "hours must be between 0 and 72")
    return await _control(
        request, lambda s, now: s.controller.set_mode(body.key, body.mode, body.hours, now)
    )


@router.post("/api/control/number")
async def set_number(body: NumberBody, request: Request) -> dict:
    return await _control(request, lambda s, now: s.controller.set_number(body.key, body.value))


@router.post("/api/control/dose")
async def dose(body: KeyBody, request: Request) -> dict:
    """Run a dose pump once. Soil pumps go through the watering limits."""

    async def action(state, now: float) -> None:
        pot = next((p for p in state.watering.pots.values() if p.pump == body.key), None)
        if pot is not None:
            await state.watering.water_now(pot.sensor, now)
        else:
            await state.controller.dose(body.key, "manual", now)

    return await _control(request, action)


@router.post("/api/control/leak/clear")
async def clear_leak(request: Request) -> dict:
    return await _control(request, lambda s, now: s.controller.clear_leak_alarm())


@router.post("/api/watering/mode")
async def watering_mode(body: PotModeBody, request: Request) -> dict:
    async def action(state, now: float) -> None:
        state.watering.set_mode(body.key, body.mode)

    return await _control(request, action)


@router.post("/api/watering/unlock")
async def watering_unlock(body: KeyBody, request: Request) -> dict:
    async def action(state, now: float) -> None:
        state.watering.unlock(body.key)

    return await _control(request, action)


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
            "control": control_view(ws.app.state, time.time()),
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
