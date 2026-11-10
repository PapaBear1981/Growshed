from growshed.ingest import Ingest
from growshed.state import LiveState
from growshed.ws import WebSocketHub


class FakeSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("gone")
        self.sent.append(message)


def make():
    state, hub = LiveState(), WebSocketHub()
    return Ingest(state, hub), state, hub


async def test_sensor_value_updates_state_and_broadcasts():
    ingest, state, hub = make()
    ws = FakeSocket()
    hub.add(ws)
    await ingest.handle("growshed/tent1/sensor/air_temp/state", "24.31", now=100.0)
    assert state.values["tent1/sensor/air_temp"] == {"value": 24.31, "ts": 100.0}
    assert state.nodes["tent1"]["last_seen"] == 100.0
    assert ws.sent == [
        {"type": "value", "key": "tent1/sensor/air_temp", "value": 24.31, "ts": 100.0}
    ]


async def test_failed_sensor_read_becomes_none():
    ingest, state, _ = make()
    await ingest.handle("growshed/tent1/sensor/air_temp/state", "24.3", now=1.0)
    await ingest.handle("growshed/tent1/sensor/air_temp/state", "nan", now=2.0)
    assert state.values["tent1/sensor/air_temp"] == {"value": None, "ts": 2.0}


async def test_node_status():
    ingest, state, hub = make()
    ws = FakeSocket()
    hub.add(ws)
    await ingest.handle("growshed/water/status", "online", now=5.0)
    assert state.nodes["water"] == {"status": "online", "last_seen": 5.0}
    await ingest.handle("growshed/water/status", "offline", now=9.0)
    assert state.nodes["water"] == {"status": "offline", "last_seen": 5.0}
    assert ws.sent[-1] == {"type": "node", "id": "water", "status": "offline", "last_seen": 5.0}


async def test_irrelevant_topics_ignored():
    ingest, state, _ = make()
    await ingest.handle("growshed/hub/heartbeat", "123")
    await ingest.handle("growshed/tent1/switch/lights/command", "ON")
    await ingest.handle("somewhere/else", "x")
    assert state.values == {} and state.nodes == {}


async def test_dead_client_does_not_block_others():
    ingest, _, hub = make()
    dead, alive = FakeSocket(fail=True), FakeSocket()
    hub.add(dead)
    hub.add(alive)
    await ingest.handle("growshed/tent1/binary_sensor/leak/state", "ON", now=1.0)
    await ingest.handle("growshed/tent1/binary_sensor/leak/state", "OFF", now=2.0)
    assert [m["value"] for m in alive.sent] == [True, False]
