import anyio
import pytest

from growshed import db
from growshed.calibration import Calibrations
from growshed.config import load_config
from growshed.control import Controller, Refused
from growshed.mqtt import MqttLink, NotConnected
from growshed.state import LiveState
from growshed.watering import Watering

T0 = 2_000_000.0
LIGHTS = "tent1/switch/lights"
SOIL = "tent2/sensor/soil_1"
PUMP = "tent2/switch/water_1"
TANK = "tent2/binary_sensor/water_tank_low"
DOSE_TOPIC = "growshed/tent2/dose/water_1/command"


class FakeLink(MqttLink):
    """Records what the hub would send to the nodes."""

    def __init__(self):
        super().__init__()
        self.sent = []
        self.down = False

    async def publish(self, topic, payload, retain=False):
        if self.down:
            raise NotConnected
        self.sent.append((topic, payload, retain))


@pytest.fixture
def rig(settings, tmp_path):
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)
    site = load_config(settings.config_path)
    live = LiveState()
    link = FakeLink()
    controller = Controller(conn, site, live, link)
    cal = Calibrations(conn, {s.state_key: s.kind for s in site.sensors})
    cal.set_point(SOIL, "dry", 2.6, T0)
    cal.set_point(SOIL, "wet", 1.2, T0)
    watering = Watering(conn, site, live, cal, controller)

    class Rig:
        pass

    r = Rig()
    r.conn, r.site, r.live, r.link, r.controller, r.cal, r.watering = (
        conn, site, live, link, controller, cal, watering,
    )  # fmt: skip

    def soil(percent, ts):
        raw = 2.6 - percent / 100 * 1.4
        live.set_value(SOIL, cal.apply(SOIL, raw), ts, raw=raw)

    r.soil = soil
    live.set_value(TANK, False, T0)
    return r


def run(fn, *args):
    return anyio.run(fn, *args)


# ---------------------------------------------------------------- modes and settings
def test_manual_mode_is_sent_and_expires_back_to_auto(rig):
    c = rig.controller
    run(c.set_mode, LIGHTS, "on", 2, T0)
    assert rig.link.sent == [("growshed/tent1/select/lights_mode/command", "on", False)]
    assert c.overrides() == {LIGHTS: {"mode": "on", "expires_at": T0 + 7200}}
    run(c.tick, T0 + 7199)
    assert len(rig.link.sent) == 1
    run(c.tick, T0 + 7201)
    assert rig.link.sent[-1] == ("growshed/tent1/select/lights_mode/command", "auto", False)
    assert c.overrides() == {}


def test_mode_without_duration_stays_and_auto_clears_any_timer(rig):
    c = rig.controller
    run(c.set_mode, LIGHTS, "off", None, T0)
    assert c.overrides() == {}
    run(c.tick, T0 + 10**6)
    assert len(rig.link.sent) == 1
    run(c.set_mode, LIGHTS, "on", 1, T0)
    run(c.set_mode, LIGHTS, "auto", None, T0)
    assert c.overrides() == {}


def test_expiry_is_retried_while_the_broker_is_down(rig):
    c = rig.controller
    run(c.set_mode, LIGHTS, "on", 1, T0)
    rig.link.down = True
    with pytest.raises(NotConnected):
        run(c.tick, T0 + 4000)
    assert LIGHTS in c.overrides()  # not forgotten
    rig.link.down = False
    run(c.tick, T0 + 4010)
    assert c.overrides() == {} and rig.link.sent[-1][1] == "auto"


def test_bad_mode_requests_are_refused(rig):
    c = rig.controller
    for key, mode in ((PUMP, "on"), ("nope/switch/x", "on"), (LIGHTS, "blink")):
        with pytest.raises(Refused):
            run(c.set_mode, key, mode, None, T0)
    assert rig.link.sent == []


def test_settings_are_range_checked(rig):
    c = rig.controller
    run(c.set_number, "water/number/water_setpoint", 21.5)
    assert rig.link.sent == [("growshed/water/number/water_setpoint/command", "21.5", False)]
    for key, value in (("water/number/water_setpoint", 30), ("water/number/nope", 1)):
        with pytest.raises(Refused):
            run(c.set_number, key, value)
    assert len(rig.link.sent) == 1


# ---------------------------------------------------------------- leak alarm
def test_leak_alarm_latches_and_needs_a_human_and_dry_sensors(rig):
    c = rig.controller
    run(c.tick, T0)
    assert not c.leak_alarm
    rig.live.set_value("tent3/binary_sensor/leak", True, T0 + 1)
    run(c.tick, T0 + 2)
    assert c.leak_alarm and rig.link.sent[-1] == ("growshed/hub/leak_alarm", "ON", True)
    with pytest.raises(Refused):
        run(c.clear_leak_alarm)
    rig.live.set_value("tent3/binary_sensor/leak", False, T0 + 3)
    run(c.tick, T0 + 4)
    assert c.leak_alarm  # drying out does not clear it by itself
    run(c.clear_leak_alarm)
    assert not c.leak_alarm and rig.link.sent[-1] == ("growshed/hub/leak_alarm", "OFF", True)


def test_leak_alarm_latches_even_with_the_broker_down_and_survives_restart(rig):
    rig.live.set_value("water/binary_sensor/leak_res", True, T0)
    rig.link.down = True
    with pytest.raises(NotConnected):
        run(rig.controller.tick, T0)
    assert rig.controller.leak_alarm
    restarted = Controller(rig.conn, rig.site, LiveState(), FakeLink())
    assert restarted.leak_alarm
    run(restarted.on_connect)
    assert restarted.link.sent == [("growshed/hub/leak_alarm", "ON", True)]


def test_no_doses_during_a_leak_alarm(rig):
    rig.live.set_value("tent1/binary_sensor/leak", True, T0)
    run(rig.controller.tick, T0)
    with pytest.raises(Refused):
        run(rig.controller.dose, "water/switch/top_off", "manual", T0)
    with pytest.raises(Refused):
        run(rig.controller.dose, LIGHTS, "manual", T0)  # not a dose pump at all


# ---------------------------------------------------------------- watering (SAFETY §4b)
def doses(rig):
    return [m for m in rig.link.sent if m[0] == DOSE_TOPIC]


def test_pots_start_off_and_auto_needs_calibration(rig):
    w = rig.watering
    assert all(p["mode"] == "off" for p in w.status(T0))
    rig.soil(10, T0)
    run(w.tick, T0)
    assert doses(rig) == []  # OFF means off, however dry
    with pytest.raises(Refused):
        w.set_mode("tent2/sensor/soil_2", "auto")  # that sensor is not calibrated
    w.set_mode(SOIL, "auto")
    assert w.status(T0)[0]["mode"] == "auto"


def test_auto_waters_in_spaced_doses_and_stops_when_wet(rig):
    w = rig.watering
    w.set_mode(SOIL, "auto")
    rig.soil(50, T0)
    run(w.tick, T0)
    assert doses(rig) == []  # above the 35 % threshold
    rig.soil(30, T0 + 10)
    run(w.tick, T0 + 10)
    assert doses(rig) == [(DOSE_TOPIC, "8", False)]
    rig.soil(30, T0 + 600)
    run(w.tick, T0 + 600)
    assert len(doses(rig)) == 1  # still soaking: no second dose yet
    rig.soil(33, T0 + 1900)  # rose by 3 points, still under 35
    run(w.tick, T0 + 1900)
    assert len(doses(rig)) == 2
    rig.soil(41, T0 + 3800)
    run(w.tick, T0 + 3800)
    assert len(doses(rig)) == 2 and w.status(T0 + 3800)[0]["locked"] is None


def test_no_response_after_two_doses_stops_auto_watering(rig):
    """The sensor fell out of the pot: it reads dry however much we water."""
    w = rig.watering
    w.set_mode(SOIL, "auto")
    for t in (0, 1900, 3800, 5700, 7600):
        rig.soil(20, T0 + t)
        run(w.tick, T0 + t)
    assert len(doses(rig)) == 2  # two doses, then stop for good
    assert "did not get wetter" in w.status(T0 + 7600)[0]["locked"]
    w.unlock(SOIL)
    rig.soil(20, T0 + 9000)
    run(w.tick, T0 + 9000)
    assert len(doses(rig)) == 3  # a human re-enabled it


def test_no_dose_is_not_judged_twice_after_a_restart(rig):
    w = rig.watering
    w.set_mode(SOIL, "auto")
    rig.soil(20, T0)
    run(w.tick, T0)
    rig.soil(20, T0 + 1900)
    run(w.tick, T0 + 1900)  # strike 1, and the second dose goes out
    restarted = Watering(rig.conn, rig.site, rig.live, rig.cal, rig.controller)
    run(restarted.tick, T0 + 1910)
    assert restarted.status(T0 + 1910)[0]["locked"] is None  # still one strike, not two


def test_daily_cap_locks_out(rig):
    w = rig.watering
    w.set_mode(SOIL, "auto")
    t = 0
    level = 10.0
    for _ in range(8):
        rig.soil(level, T0 + t)
        run(w.tick, T0 + t)
        level += 3  # responds each time, but never reaches the threshold
        t += 1900
    assert len(doses(rig)) == 6
    assert "maximum number of doses" in w.status(T0 + t)[0]["locked"]


def test_auto_watering_refuses_untrustworthy_readings_and_unsafe_conditions(rig):
    w = rig.watering
    w.set_mode(SOIL, "auto")
    # stale reading
    rig.soil(10, T0)
    run(w.tick, T0 + 400)
    # reading far outside the calibrated range (sensor in mid-air reads drier than "dry")
    rig.live.set_value(SOIL, 0.0, T0 + 500, raw=2.9)
    run(w.tick, T0 + 500)
    # tank low, then tank sensor missing
    rig.soil(10, T0 + 600)
    rig.live.set_value(TANK, True, T0 + 600)
    run(w.tick, T0 + 600)
    del rig.live.values[TANK]
    run(w.tick, T0 + 610)
    # leak alarm
    rig.live.set_value(TANK, False, T0 + 620)
    rig.live.set_value("tent1/binary_sensor/leak", True, T0 + 620)
    run(rig.controller.tick, T0 + 620)
    run(w.tick, T0 + 630)
    assert doses(rig) == []
    assert w.status(T0 + 630)[0]["blocked"] == "leak alarm active"


def test_water_now_obeys_the_limits_but_not_the_threshold(rig):
    w = rig.watering
    rig.soil(80, T0)  # nowhere near dry: a manual dose is still allowed
    run(w.water_now, SOIL, T0)
    assert len(doses(rig)) == 1
    with pytest.raises(Refused, match="soak"):
        run(w.water_now, SOIL, T0 + 60)
    rig.live.set_value(TANK, True, T0 + 2000)
    with pytest.raises(Refused, match="tank"):
        run(w.water_now, SOIL, T0 + 2000)
    with pytest.raises(Refused):
        run(w.water_now, "tent2/sensor/nope", T0)
    assert len(doses(rig)) == 1
    row = rig.conn.execute("SELECT source, pre_value FROM dose_event").fetchone()
    assert (row["source"], row["pre_value"]) == ("manual", 80.0)
