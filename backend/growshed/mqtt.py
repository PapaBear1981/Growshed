"""MQTT connection: subscribe to every node, publish the hub heartbeat.

The heartbeat matters for safety: nodes that stop hearing it for 3 minutes switch to
their built-in FALLBACK behaviour (docs/SAFETY.md §2). So it is published from its own
task and never blocked by message handling.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiomqtt

from . import topics
from .config import Settings
from .ingest import Ingest

log = logging.getLogger(__name__)
RECONNECT_DELAY_S = 5.0


async def _heartbeat(client: aiomqtt.Client, interval_s: float) -> None:
    while True:
        await client.publish(topics.HEARTBEAT_TOPIC, str(int(time.time())))
        await asyncio.sleep(interval_s)


async def _set_connected(ingest: Ingest, connected: bool) -> None:
    ingest.state.mqtt_connected = connected
    await ingest.hub.broadcast({"type": "hub", "mqtt_connected": connected})


async def run_mqtt(settings: Settings, ingest: Ingest) -> None:
    """Run forever, reconnecting after any broker outage."""
    will = aiomqtt.Will(topics.HUB_STATUS_TOPIC, "offline", qos=1, retain=True)
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_user,
                password=settings.mqtt_password,
                identifier="growshed-backend",
                will=will,
            ) as client:
                log.info("MQTT connected to %s:%s", settings.mqtt_host, settings.mqtt_port)
                await client.publish(topics.HUB_STATUS_TOPIC, "online", qos=1, retain=True)
                await client.subscribe(f"{topics.PREFIX}/#")
                await _set_connected(ingest, True)
                beat = asyncio.create_task(_heartbeat(client, settings.heartbeat_interval_s))
                try:
                    async for message in client.messages:
                        payload = message.payload
                        text = (
                            payload.decode("utf-8", "replace")
                            if isinstance(payload, bytes | bytearray)
                            else str(payload)
                        )
                        try:
                            await ingest.handle(str(message.topic), text)
                        except Exception:
                            # One malformed message must never take the ingest loop down.
                            log.exception("failed to handle %s", message.topic)
                finally:
                    beat.cancel()
        except aiomqtt.MqttError as exc:
            log.warning("MQTT connection lost (%s); retrying in %ss", exc, RECONNECT_DELAY_S)
        finally:
            await _set_connected(ingest, False)
        await asyncio.sleep(RECONNECT_DELAY_S)
