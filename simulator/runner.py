"""Runs each simulated node as its own MQTT client, like a real ESP32 would be."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import aiomqtt

from .model import NodeModel, TentModel, build_models

log = logging.getLogger("simulator")
PREFIX = "growshed"
HEARTBEAT_TOPIC = f"{PREFIX}/hub/heartbeat"
LEAK_ALARM_TOPIC = f"{PREFIX}/hub/leak_alarm"
HEARTBEAT_TIMEOUT_S = 180  # SAFETY.md: no heartbeat for 3 minutes -> FALLBACK


class SimClock:
    """Simulated time. --speed 60 makes one real second count as a simulated minute."""

    def __init__(self, speed: float) -> None:
        self.speed = speed
        self._start = time.time()

    def now(self) -> float:
        return self._start + (time.time() - self._start) * self.speed

    def hour(self) -> float:
        lt = time.localtime(self.now())
        return lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600


class SimNode:
    def __init__(self, node_id: str, model: NodeModel, clock: SimClock, interval_s: float) -> None:
        self.id = node_id
        self.model = model
        self.clock = clock
        self.interval_s = interval_s
        self.base = f"{PREFIX}/{node_id}"
        self.offline = False
        self.started = time.time()
        self.last_heartbeat: float | None = None

    def heartbeat_age(self) -> float:
        return time.time() - (self.last_heartbeat or self.started)

    async def publish_all(self, client: aiomqtt.Client) -> None:
        age = self.heartbeat_age()
        self.model.fallback = age > HEARTBEAT_TIMEOUT_S
        diagnostics = [
            ("text_sensor", "mode", "fallback" if self.model.fallback else "normal"),
            ("sensor", "wifi_rssi", f"{-55 + self.model.rng.gauss(0, 2):.0f}"),
            ("sensor", "uptime", f"{time.time() - self.started:.0f}"),
            ("sensor", "heartbeat_age", f"{age:.0f}"),
            ("text_sensor", "board", "Simulated board"),
            ("text_sensor", "firmware", "simulator"),
        ]
        for component, entity, payload in self.model.entities() + diagnostics:
            await client.publish(f"{self.base}/{component}/{entity}/state", payload)

    async def on_message(self, client: aiomqtt.Client, topic: str, payload: str) -> None:
        if topic == HEARTBEAT_TOPIC:
            self.last_heartbeat = time.time()
            return
        if topic == f"{PREFIX}/sim/{self.id}/fault":
            text = payload.strip().lower()
            if text in ("offline", "online"):
                self.offline = text == "offline"
                await client.publish(f"{self.base}/status", text, qos=1, retain=True)
            elif not self.model.fault(text):
                log.warning("%s: unknown fault %r", self.id, text)
                return
            log.info("%s: fault %r", self.id, text)
        elif topic == LEAK_ALARM_TOPIC:
            self.model.hub_leak = payload.strip().upper() == "ON"
        elif topic.endswith("/command"):
            component, entity = topic.split("/")[-3:-1]
            text = payload.strip()
            try:
                if component == "select":
                    ok = self.model.set_mode(entity.removesuffix("_mode"), text)
                elif component == "number":
                    ok = self.model.set_number(entity, float(text))
                elif component == "dose":
                    ok = self.model.request_dose(entity, float(text))
                elif component == "prime":
                    ok = getattr(self.model, "request_prime", lambda *a: False)(entity, float(text))
                else:
                    ok = False  # like the firmware, direct switch commands are ignored
            except ValueError:
                ok = False
            if not ok:
                return
            log.info("%s: %s/%s <- %s", self.id, component, entity, text)
        else:
            return
        if not self.offline:  # echo the new state straight away, as ESPHome does
            self.model.step(0, self.clock.hour())
            await self.publish_all(client)

    async def listen(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            payload = message.payload
            text = payload.decode() if isinstance(payload, bytes | bytearray) else str(payload)
            await self.on_message(client, str(message.topic), text)

    async def run(self, args: argparse.Namespace) -> None:
        will = aiomqtt.Will(f"{self.base}/status", "offline", qos=1, retain=True)
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=args.host,
                    port=args.port,
                    username=args.user,
                    password=args.password,
                    identifier=f"growshed-sim-{self.id}",
                    will=will,
                ) as client:
                    await client.publish(f"{self.base}/status", "online", qos=1, retain=True)
                    for component in ("select", "number", "dose", "prime"):
                        await client.subscribe(f"{self.base}/{component}/+/command")
                    await client.subscribe(LEAK_ALARM_TOPIC)
                    await client.subscribe(f"{PREFIX}/sim/{self.id}/fault")
                    await client.subscribe(HEARTBEAT_TOPIC)
                    log.info("%s: connected", self.id)
                    listener = asyncio.create_task(self.listen(client))
                    try:
                        while not listener.done():
                            self.model.step(self.interval_s * self.clock.speed, self.clock.hour())
                            if not self.offline:
                                await self.publish_all(client)
                            await asyncio.sleep(self.interval_s)
                        listener.result()
                    finally:
                        listener.cancel()
            except aiomqtt.MqttError as exc:
                log.warning("%s: MQTT error (%s); retrying in 5 s", self.id, exc)
                await asyncio.sleep(5)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = os.environ
    p = argparse.ArgumentParser(prog="simulator", description=__doc__)
    p.add_argument("--host", default=env.get("GROWSHED_MQTT_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(env.get("GROWSHED_MQTT_PORT", "1883")))
    p.add_argument("--user", default=env.get("GROWSHED_MQTT_USER") or None)
    p.add_argument("--password", default=env.get("GROWSHED_MQTT_PASSWORD") or None)
    p.add_argument("--interval", type=float, default=5.0, help="seconds between publishes")
    p.add_argument("--speed", type=float, default=1.0, help="time acceleration factor")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--extra-node",
        action="append",
        default=[],
        metavar="ID",
        help="also simulate a tent node that is NOT in config.yaml (tests auto-discovery)",
    )
    return p.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    clock = SimClock(args.speed)
    models = build_models(args.seed)
    for extra in args.extra_node:
        models[extra] = TentModel(args.seed + len(models) + 1)
    nodes = [SimNode(i, m, clock, args.interval) for i, m in models.items()]
    await asyncio.gather(*(node.run(args) for node in nodes))
