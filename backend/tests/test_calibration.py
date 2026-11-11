import anyio
import pytest

from growshed import db
from growshed.calibration import (
    Calibrations,
    compensate_ec_volts,
    ec_from_volts,
)

SOIL = "tent2/sensor/soil_1"
TEMP = "tent1/sensor/air_temp"
RH = "tent1/sensor/air_rh"
PH = "water/sensor/ph"
EC = "water/sensor/ec"
LUX = "tent1/sensor/light_lux"
KINDS = {SOIL: "soil_moisture", TEMP: "temperature", RH: "humidity", PH: "ph", EC: "ec",
         LUX: "illuminance"}  # fmt: skip
T0 = 3_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "x.db")
    db.migrate(c)
    return c


@pytest.fixture
def cal(conn):
    return Calibrations(conn, KINDS, water_temp=lambda key: 20.0)


# ---------------------------------------------------------------- soil
def test_uncalibrated_required_sensors_have_no_value(cal):
    for key in (SOIL, PH, EC):
        assert cal.apply(key, 1.9) is None  # never a guessed number
    assert cal.apply(LUX, 500.0) == 500.0  # sensors without calibration pass through
    assert cal.apply(TEMP, 21.5) == 21.5  # offsets are optional
    cal.set_point(SOIL, "dry", 2.6, T0)
    assert cal.apply(SOIL, 1.9) is None and not cal.is_calibrated(SOIL)  # one point is not enough


def test_soil_two_point(cal):
    cal.set_point(SOIL, "dry", 2.6, T0)
    cal.set_point(SOIL, "wet", 1.2, T0)
    assert [cal.apply(SOIL, v) for v in (2.6, 1.2, 1.9, 2.9, 0.9)] == [0.0, 100.0, 50.0, 0.0, 100.0]
    assert cal.raw_percent(SOIL, 2.9) < -10  # unclamped: a sensor out of the soil is visible
    assert cal.apply(SOIL, None) is None
    with pytest.raises(ValueError):
        cal.set_point(SOIL, "damp", 2.0, T0)


def test_soil_points_too_close_are_flagged(cal):
    cal.set_point(SOIL, "dry", 2.60, T0)
    cal.set_point(SOIL, "wet", 2.55, T0)  # pressed "wet" while still in air
    assert not cal.is_calibrated(SOIL) and cal.apply(SOIL, 2.0) is None
    assert "almost the same" in cal.warning(SOIL)


# ---------------------------------------------------------------- pH
def test_ph_needs_two_buffers_then_fits_a_line(cal):
    cal.set_point(PH, "ph", 2.50, T0, ref=7.0)
    assert not cal.is_calibrated(PH) and cal.apply(PH, 2.5) is None
    cal.set_point(PH, "ph", 3.04, T0, ref=4.0)  # cheap boards: lower pH = higher volts
    assert cal.is_calibrated(PH)
    assert cal.apply(PH, 2.50) == 7.0 and cal.apply(PH, 3.04) == 4.0
    assert cal.apply(PH, 2.77) == pytest.approx(5.5, abs=0.01)
    assert cal.apply(PH, 9.0) == 0.0  # clamped to the pH scale


def test_ph_new_point_replaces_the_nearby_buffer(cal):
    cal.set_point(PH, "ph", 2.50, T0, ref=7.0)
    cal.set_point(PH, "ph", 2.52, T0 + 10, ref=6.86)  # powder buffer instead of 7.00
    assert sorted(cal.points[PH]) == ["ph6.86"]
    cal.set_point(PH, "ph", 3.03, T0, ref=4.01)
    cal.set_point(PH, "ph", 2.13, T0, ref=9.18)
    assert sorted(cal.points[PH]) == ["ph4.01", "ph6.86", "ph9.18"]
    assert cal.warning(PH) is None


def test_ph_bad_calibrations_are_caught(cal):
    with pytest.raises(ValueError):
        cal.set_point(PH, "ph", 2.5, T0)  # which buffer?
    with pytest.raises(ValueError):
        cal.set_point(PH, "ph", 2.5, T0, ref=20)
    cal.set_point(PH, "ph", 2.50, T0, ref=7.0)
    cal.set_point(PH, "ph", 2.52, T0, ref=4.0)  # probe not rinsed / still in the first buffer
    assert not cal.is_calibrated(PH) and "almost the same" in cal.warning(PH)
    # three points that do not line up: a worn-out probe
    cal.clear(PH)
    for volts, ref in ((2.50, 7.0), (3.04, 4.0), (2.45, 10.0)):
        cal.set_point(PH, "ph", volts, T0, ref=ref)
    assert cal.is_calibrated(PH) and "worn out" in cal.warning(PH)


# ---------------------------------------------------------------- EC
def test_ec_one_point_scale_and_temperature_compensation(conn):
    temps = {"t": 25.0}
    cal = Calibrations(conn, KINDS, water_temp=lambda key: temps["t"])
    volts = 1.6
    cal.set_point(EC, "ec", cal.prepare(EC, volts), T0, ref=1413)
    assert cal.apply(EC, cal.prepare(EC, volts)) == 1413
    # The same solution warmed by 5 °C conducts ~10 % more: the reading must not move.
    temps["t"] = 30.0
    warmer_volts = volts * 1.10
    assert cal.apply(EC, cal.prepare(EC, warmer_volts)) == pytest.approx(1413, rel=0.01)
    assert compensate_ec_volts(1.1, 25.0) == 1.1
    assert ec_from_volts(0) == 0


def test_ec_without_water_temperature_has_no_value(conn):
    cal = Calibrations(conn, KINDS)  # no temperature available
    assert cal.prepare(EC, 1.6) is None
    assert cal.prepare(PH, 2.5) == 2.5  # only EC depends on it


def test_ec_refuses_nonsense(cal):
    with pytest.raises(ValueError, match="solution"):
        cal.set_point(EC, "ec", 0.01, T0, ref=1413)  # probe in air
    with pytest.raises(ValueError):
        cal.set_point(EC, "ec", 1.6, T0, ref=5)


# ---------------------------------------------------------------- offsets
def test_temperature_and_humidity_offsets(cal):
    cal.set_point(TEMP, "offset", 21.8, T0, ref=21.0)
    assert cal.apply(TEMP, 21.8) == 21.0 and cal.apply(TEMP, 25.0) == 24.2
    cal.set_point(RH, "offset", 55.0, T0, ref=60.0)
    assert cal.apply(RH, 50.0) == 55.0
    with pytest.raises(ValueError, match="faulty"):
        cal.set_point(TEMP, "offset", 21.8, T0, ref=30.0)  # 8 °C off is not a calibration job
    with pytest.raises(ValueError):
        cal.set_point(LUX, "offset", 100, T0, ref=120)


# ---------------------------------------------------------------- automatic capture
def test_capture_waits_for_enough_steady_readings(cal):
    assert cal.capture(SOIL, "dry", None, T0)["status"] == "waiting"
    for i, volts in enumerate((2.30, 2.45, 2.58)):  # probe just lifted out: still moving
        cal.observe(SOIL, volts, T0 + i * 20)
    result = cal.capture(SOIL, "dry", None, T0 + 45)
    assert result["status"] == "waiting" and "settling" in result["reason"]
    for i, volts in enumerate((2.600, 2.604, 2.598)):
        cal.observe(SOIL, volts, T0 + 120 + i * 20)
    assert cal.capture(SOIL, "dry", None, T0 + 165) == {"status": "saved"}
    assert cal.points[SOIL]["dry"]["raw"] == pytest.approx(2.6007, abs=0.001)  # the average


def test_capture_ignores_old_readings(cal):
    for i in range(5):
        cal.observe(PH, 2.5, T0 + i)
    assert cal.capture(PH, "ph", 7.0, T0 + 500)["status"] == "waiting"


def test_calibration_survives_restart_and_reports_age(conn, cal):
    cal.set_point(PH, "ph", 2.50, T0, ref=7.0)
    cal.set_point(PH, "ph", 3.04, T0 + 86400, ref=4.0)
    again = Calibrations(conn, KINDS)
    assert again.apply(PH, 2.77) == pytest.approx(5.5, abs=0.01)
    assert again.age_days(PH, T0 + 10 * 86400) == pytest.approx(10)  # the oldest point counts
    assert again.age_days(EC, T0) is None
    summary = again.summary()
    assert summary[PH]["calibrated"] and summary[PH]["max_age_days"] == 30
    assert summary[TEMP]["required"] is False and LUX not in summary


def test_migration_keeps_existing_soil_calibrations(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE schema_migration (name TEXT PRIMARY KEY, applied_at INTEGER)")
    for name in ("001_settings.sql", "002_history_alerts.sql", "003_calibration.sql",
                 "004_control.sql"):  # fmt: skip
        conn.executescript((db.MIGRATIONS_DIR / name).read_text())
        conn.execute("INSERT INTO schema_migration VALUES (?, 0)", (name,))
    conn.execute("INSERT INTO calibration VALUES (?, 2.6, 1.2, 99)", (SOIL,))
    conn.commit()
    db.migrate(conn)
    assert Calibrations(conn, KINDS).apply(SOIL, 1.9) == 50.0


# ---------------------------------------------------------------- through the API
def feed(client, topic, payloads, start):
    for i, payload in enumerate(payloads):
        anyio.run(client.app.state.ingest.handle, topic, payload, start + i * 5)


def test_api_soil_flow_values_history_and_alert(client):
    app = client.app
    live = app.state.live
    topic = "growshed/tent2/sensor/soil_1/state"
    import time

    now = time.time() - 60
    assert client.get("/api/calibration").json()[SOIL]["calibrated"] is False
    body = {"key": SOIL, "label": "dry"}
    assert client.post("/api/calibration", json=body).json()["status"] == "waiting"
    assert (
        client.post(
            "/api/calibration", json={"key": "tent1/sensor/light_lux", "label": "dry"}
        ).status_code
        == 404
    )

    feed(client, topic, ["2.600", "2.601", "2.599"], now)
    assert live.values[SOIL]["value"] is None and live.values[SOIL]["raw"] == 2.599
    assert client.post("/api/calibration", json=body).json() == {"status": "saved"}
    feed(client, topic, ["1.900", "1.300"], now + 20)
    # Just moved into the water: the newest readings disagree, so nothing is saved yet.
    waiting = client.post("/api/calibration", json={"key": SOIL, "label": "wet"}).json()
    assert waiting["status"] == "waiting"
    feed(client, topic, ["1.200", "1.201", "1.199"], now + 40)
    assert client.post("/api/calibration", json={"key": SOIL, "label": "wet"}).json() == {
        "status": "saved"
    }
    assert live.values[SOIL]["value"] == 100.0  # recomputed immediately

    anyio.run(app.state.ingest.handle, topic, "2.320", now + 55)
    assert live.values[SOIL]["value"] == 20.0
    app.state.recorder.flush()
    hist = client.get(
        "/api/history", params={"keys": SOIL, "start": now - 60, "end": now + 120}
    ).json()
    values = [v for v in hist["series"][SOIL] if v is not None]
    assert values and all(0 <= v <= 100 for v in values)  # stored as volts, served as percent

    engine = app.state.alerts
    live.set_node_status("tent2", "online", now + 55)
    engine.tick(now + 56)
    anyio.run(app.state.ingest.handle, topic, "2.320", now + 1900)
    notes = engine.tick(now + 1901)
    assert [n.body for n in notes if "Soil dry" in n.title] == [
        "Soil pots · Pot 1: 20 % (limit 30 %)"
    ]

    assert client.delete("/api/calibration", params={"key": SOIL}).json() == {"status": "cleared"}
    assert live.values[SOIL]["value"] is None


def test_api_refuses_impossible_points(client):
    import time

    feed(client, "growshed/tent1/sensor/air_temp/state", ["21.8", "21.8", "21.8"], time.time() - 30)
    bad = client.post("/api/calibration", json={"key": TEMP, "label": "offset", "ref": 35})
    assert bad.status_code == 409 and "faulty" in bad.json()["detail"]
    ok = client.post("/api/calibration", json={"key": TEMP, "label": "offset", "ref": 21.0})
    assert ok.json() == {"status": "saved"}
    assert client.app.state.live.values[TEMP]["value"] == 21.0


def test_uncalibrated_sensor_is_not_reported_as_dead(client):
    app = client.app
    now = app.state.alerts.started_at
    app.state.live.set_node_status("tent2", "online", now)
    for t in range(0, 1300, 60):
        anyio.run(app.state.ingest.handle, "growshed/tent2/sensor/soil_2/state", "2.1", now + t)
    notes = app.state.alerts.tick(now + 1300)
    assert not [n for n in notes if "Pot 2" in n.body]  # reporting, just not calibrated
