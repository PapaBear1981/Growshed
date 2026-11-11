"""In-memory picture of the garden right now: latest value of every entity, node status."""

from __future__ import annotations

from typing import Any


class LiveState:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}  # key -> {"value", "ts"}
        self.last_valid: dict[str, float] = {}  # key -> ts of the last usable (non-None) value
        self.nodes: dict[str, dict[str, Any]] = {}  # node id -> {"status", "last_seen"}
        self.mqtt_connected = False

    def set_value(self, key: str, value: Any, ts: float) -> None:
        self.values[key] = {"value": value, "ts": ts}
        if value is not None:
            self.last_valid[key] = ts

    def touch_node(self, node: str, ts: float) -> None:
        entry = self.nodes.setdefault(node, {"status": "unknown", "last_seen": None})
        entry["last_seen"] = ts

    def set_node_status(self, node: str, status: str, ts: float) -> None:
        entry = self.nodes.setdefault(node, {"status": "unknown", "last_seen": None})
        entry["status"] = status
        if status == "online":
            entry["last_seen"] = ts

    def snapshot(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "nodes": self.nodes,
            "mqtt_connected": self.mqtt_connected,
        }
