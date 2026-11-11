import anyio
import pytest

from growshed import db
from growshed.calibration import Calibrations

SOIL = "tent2/sensor/soil_1"
TEMP = "tent1/sensor/air_temp"
KINDS = {SOIL: "soil_moisture", TEMP: "temperature"}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "x.db")
    db.migrate(c)
    return c


def test_uncalibrated_soil_sensor_has_no_value(conn):
    cal = Calibrations(conn, KINDS)
    assert cal.apply(SOIL, 1.9) is None  # never a guessed percentage
    assert cal.apply(TEMP, 21.5) == 21.5  # other sensors pass straight through
    cal.set_point(SOIL, "dry", 2.6, 100)
    assert cal.apply(SOIL, 1.9) is None and not cal.is_calibrated(SOIL)  # one point is not enough


def test_two_point_calibration(conn):
    cal = Calibrations(conn, KINDS)
    cal.set_point(SOIL, "dry", 2.6, 100)
    cal.set_point(SOIL, "wet", 1.2, 110)
    assert cal.apply(SOIL, 2.6) == 0.0
    assert cal.apply(SOIL, 1.2) == 100.0
    assert cal.apply(SOIL, 1.9) == 50.0
    assert cal.apply(SOIL, 2.9) == 0.0 and cal.apply(SOIL, 0.9) == 100.0  # clamped
    assert cal.apply(SOIL, None) is None
    assert cal.summary() == {SOIL: {"dry": 2.6, "wet": 1.2, "calibrated": True}}


def test_points_too_close_together_are_rejected_as_a_mistake(conn):
    cal = Calibrations(conn, KINDS)
    cal.set_point(SOIL, "dry", 2.60, 100)
    cal.set_point(SOIL, "wet", 2.55, 110)  # e.g. pressed "wet" while still in air
    assert not cal.is_calibrated(SOIL) and cal.apply(SOIL, 2.0) is None
    with pytest.raises(ValueError):
        cal.set_point(SOIL, "damp", 2.0, 120)


def test_calibration_survives_restart(conn):
    first = Calibrations(conn, KINDS)
    first.set_point(SOIL, "dry", 2.6, 100)
    first.set_point(SOIL, "wet", 1.2, 110)
    assert Calibrations(conn, KINDS).apply(SOIL, 1.9) == 50.0


def test_api_flow_calibrate_then_values_history_and_alert(client):
    app = client.app
    ingest, live = app.state.ingest, app.state.live
    topic = "growshed/tent2/sensor/soil_1/state"
    now = app.state.alerts.started_at

    assert client.get("/api/calibration").json()[SOIL] == {
        "dry": None,
        "wet": None,
        "calibrated": False,
    }
    # No reading yet: nothing to calibrate against.
    assert client.post("/api/calibration", json={"key": SOIL, "point": "dry"}).status_code == 409
    assert client.post("/api/calibration", json={"key": TEMP, "point": "dry"}).status_code == 404

    anyio.run(ingest.handle, topic, "2.600", now)
    assert live.values[SOIL]["value"] is None and live.values[SOIL]["raw"] == 2.6
    assert client.post("/api/calibration", json={"key": SOIL, "point": "dry"}).status_code == 200
    anyio.run(ingest.handle, topic, "1.200", now + 20)
    body = client.post("/api/calibration", json={"key": SOIL, "point": "wet"}).json()
    assert body == {"dry": 2.6, "wet": 1.2, "calibrated": True}
    assert live.values[SOIL]["value"] == 100.0  # recomputed immediately

    anyio.run(ingest.handle, topic, "2.320", now + 40)
    assert live.values[SOIL]["value"] == 20.0

    # History stores volts and returns percent.
    app.state.recorder.flush()
    hist = client.get(
        "/api/history", params={"keys": SOIL, "start": now - 60, "end": now + 120}
    ).json()
    values = [v for v in hist["series"][SOIL] if v is not None]
    assert values and all(0 <= v <= 100 for v in values)

    # 20 % is below the "Soil dry" limit: alert after the hold time, never before.
    engine = app.state.alerts
    live.set_node_status("tent2", "online", now + 40)
    assert [n.title for n in engine.tick(now + 41)] == []
    anyio.run(ingest.handle, topic, "2.320", now + 1850)
    notes = engine.tick(now + 1851)
    assert [n.body for n in notes if "Soil dry" in n.title] == [
        "Soil pots · Pot 1: 20 % (limit 30 %)"
    ]


def test_uncalibrated_sensor_is_not_reported_as_dead(client):
    app = client.app
    now = app.state.alerts.started_at
    app.state.live.set_node_status("tent2", "online", now)
    for t in range(0, 1300, 60):
        anyio.run(app.state.ingest.handle, "growshed/tent2/sensor/soil_2/state", "2.1", now + t)
    notes = app.state.alerts.tick(now + 1300)
    assert not [n for n in notes if "Pot 2" in n.body]  # reporting, just not calibrated
