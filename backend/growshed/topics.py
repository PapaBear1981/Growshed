"""MQTT topic parsing. The contract is docs/MQTT.md (ESPHome's default topic layout)."""

from __future__ import annotations

import math
from dataclasses import dataclass

PREFIX = "growshed"
HUB = "hub"
HEARTBEAT_TOPIC = f"{PREFIX}/{HUB}/heartbeat"
HUB_STATUS_TOPIC = f"{PREFIX}/{HUB}/status"
LEAK_ALARM_TOPIC = f"{PREFIX}/{HUB}/leak_alarm"

NUMERIC_COMPONENTS = {"sensor", "number"}
BOOLEAN_COMPONENTS = {"binary_sensor", "switch"}
TEXT_COMPONENTS = {"text_sensor", "select"}
COMPONENTS = NUMERIC_COMPONENTS | BOOLEAN_COMPONENTS | TEXT_COMPONENTS


@dataclass(frozen=True)
class EntityState:
    node: str
    component: str
    entity: str

    @property
    def key(self) -> str:
        return f"{self.node}/{self.component}/{self.entity}"


def parse_state_topic(topic: str) -> EntityState | None:
    """growshed/<node>/<component>/<entity>/state -> EntityState, else None."""
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != PREFIX or parts[4] != "state":
        return None
    node, component, entity = parts[1], parts[2], parts[3]
    if node == HUB or component not in COMPONENTS or not node or not entity:
        return None
    return EntityState(node, component, entity)


def parse_status_topic(topic: str) -> str | None:
    """growshed/<node>/status -> node id (never the hub itself), else None."""
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == PREFIX and parts[2] == "status" and parts[1] != HUB:
        return parts[1] or None
    return None


def parse_payload(component: str, payload: str) -> float | bool | str | None:
    """Convert an ESPHome state payload to a typed value.

    Returns None for unusable payloads (ESPHome publishes "nan" when a sensor read
    fails). A bad reading must surface as "no value", never as a made-up number.
    """
    text = payload.strip()
    if component in NUMERIC_COMPONENTS:
        try:
            value = float(text)
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    if component in BOOLEAN_COMPONENTS:
        upper = text.upper()
        if upper == "ON":
            return True
        if upper == "OFF":
            return False
        return None
    return text
