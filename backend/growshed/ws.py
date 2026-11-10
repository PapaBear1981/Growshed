"""WebSocket fan-out to every open GUI (phones, laptop, wall tablet)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        # One dead tablet connection must not stop updates reaching the other screens.
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - any send failure means the client is gone
                log.debug("dropping dead websocket client")
                self._clients.discard(ws)
