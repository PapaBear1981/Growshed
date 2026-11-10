"""Turns incoming MQTT messages into live state and GUI updates."""

from __future__ import annotations

import time

from . import topics
from .state import LiveState
from .ws import WebSocketHub


class Ingest:
    def __init__(self, state: LiveState, hub: WebSocketHub) -> None:
        self.state = state
        self.hub = hub

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
        self.state.set_value(entity.key, value, ts)
        self.state.touch_node(entity.node, ts)
        await self.hub.broadcast({"type": "value", "key": entity.key, "value": value, "ts": ts})
