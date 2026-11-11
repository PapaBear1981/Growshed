"""Turns incoming MQTT messages into live state and GUI updates."""

from __future__ import annotations

import time

from . import topics
from .state import LiveState
from .ws import WebSocketHub


class Ingest:
    def __init__(self, state: LiveState, hub: WebSocketHub, recorder=None, calibrations=None):
        self.state = state
        self.hub = hub
        self.recorder = recorder  # optional: stores history for configured sensors
        self.calibrations = calibrations  # optional: raw -> calibrated (soil moisture)

    async def handle(self, topic: str, payload: str, now: float | None = None) -> None:
        ts = time.time() if now is None else now

        node = topics.parse_status_topic(topic)
        if node is not None:
            status = "online" if payload.strip().lower() == "online" else "offline"
            self.state.set_node_status(node, status, ts)
            await self.hub.broadcast({"type": "node", "id": node, **self.state.nodes[node]})
            return

        entity = topics.parse_state_topic(topic)
        if entity is None:
            return
        value = topics.parse_payload(entity.component, payload)
        self.state.touch_node(entity.node, ts)
        cal = self.calibrations
        if cal is not None and cal.uses(entity.key):
            value = cal.prepare(entity.key, value)  # e.g. EC referred to 25 °C
            if value is not None:
                cal.observe(entity.key, value, ts)
        if self.recorder is not None:
            self.recorder.add(entity.key, value, ts)  # history keeps the raw reading
        await self.publish(entity.key, value, ts)

    async def publish(self, key: str, raw, ts: float) -> None:
        """Update live state and the GUIs with one reading, applying any calibration."""
        message = {"type": "value", "key": key, "value": raw, "ts": ts}
        if self.calibrations is not None and self.calibrations.uses(key):
            message["value"] = self.calibrations.apply(key, raw)
            message["raw"] = raw
        self.state.set_value(key, message["value"], ts, raw=message.get("raw"))
        await self.hub.broadcast(message)
