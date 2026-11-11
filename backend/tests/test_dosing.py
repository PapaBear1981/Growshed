import anyio
import pytest
from pydantic import ValidationError

from growshed import db
from growshed.calibration import Calibrations
from growshed.config import DosingConfig, load_config
from growshed.control import Controller, Refused
from growshed.dosing import Dosing
from growshed.mqtt import MqttLink
from growshed.state import LiveState

T0 = 4_000_000.0
PH, EC = "water/sensor/ph", "water/sensor/ec"
PUMPS = ("ph_down", "ph_up", "nutrient_a", "nutrient_b")


class FakeLink(MqttLink):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))


class Rig:
    """A hub with a healthy, calibrated reservoir: everything that dosing needs is fine."""

    def __init__(self, settings, tmp_path):
        self.conn = db.connect(tmp_path / "x.db")
        db.migrate(self.conn)
        self.site = load_config(settings.config_path)
        self.live = LiveState()
        self.link = FakeLink()
        self.controller = Controller(self.conn, self.site, self.live, self.link)
        kinds = {s.state_key: s.kind for s in self.site.sensors if s.component == "sensor"}
        self.cal = Calibrations(self.conn, kinds, water_temp=lambda key: 20.0)
        self.cal.set_point(PH, "ph", 2.50, T0, ref=7.0)
        self.cal.set_point(PH, "ph", 3.04, T0, ref=4.0)
        self.cal.set_point(EC, "ec", 1.6, T0, ref=1413)
        self.dosing = Dosing(self.conn, self.site, self.live, self.cal, self.controller, self.link)
        for pump in PUMPS:
            self.live.set_value(f"dosing/number/{pump}_ml_per_s", 1.2, T0)
        self.set(6.0, 1400, T0 - 1000)

    def feed(self, ph, ec, ts):
        """One reading from each probe, and healthy nodes, at time `ts`."""
        self.live.set_value(PH, ph, ts, raw=1.0)
        self.live.set_value(EC, ec, ts, raw=1.0)
        self.live.set_value("water/switch/rdwc_pump", True, ts)
        self.live.set_value("water/binary_sensor/res_low", False, ts)
        for node in ("water", "dosing"):
            self.live.set_node_status(node, "online", ts)
        self.dosing._observe(ts)

    def set(self, ph, ec, ts):
        """The reservoir has been steadily at these values for the last minute."""
        for ago in (40, 20, 0):
            self.feed(ph, ec, ts - ago)

    def tick(self, now):
        anyio.run(self.dosing.tick, now)

    def doses(self):
        return [(t.split("/")[3], p) for t, p in self.link.sent if "/dose/" in t]


@pytest.fixture
def rig(settings, tmp_path):
    return Rig(settings, tmp_path)


def run(fn, *args):
    return anyio.run(fn, *args)


# ---------------------------------------------------------------- modes
def test_off_by_default_and_does_nothing(rig):
    assert rig.dosing.mode == "off"
    rig.set(7.5, 300, T0 + 10)  # badly out of range
    rig.tick(T0 + 10)
    assert rig.doses() == [] and rig.dosing.suggestion is None


def test_auto_requires_explicit_acknowledgement(rig):
    with pytest.raises(Refused, match="kill the plants"):
        rig.dosing.set_mode("auto", False, T0)
    assert rig.dosing.mode == "off"
    rig.dosing.set_mode("auto", True, T0)
    assert rig.dosing.mode == "auto"
    with pytest.raises(Refused):
        rig.dosing.set_mode("turbo", True, T0)


def test_modes_need_calibrated_pumps_and_probes(rig):
    rig.live.set_value("dosing/number/ph_up_ml_per_s", 0.0, T0)
    with pytest.raises(Refused, match="pH up pump"):
        rig.dosing.set_mode("suggest", False, T0)
    rig.live.set_value("dosing/number/ph_up_ml_per_s", 1.2, T0)
    rig.cal.clear(EC)
    with pytest.raises(Refused, match="EC probe"):
        rig.dosing.set_mode("auto", True, T0)
    rig.dosing.set_mode("off", False, T0)  # turning off is always allowed


# ---------------------------------------------------------------- suggest mode
def test_suggest_proposes_and_waits_for_approval(rig):
    rig.dosing.set_mode("suggest", False, T0)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    s = rig.dosing.suggestion
    assert (s["kind"], s["ml"]) == ("ph_down", 1.0) and "6.6" in s["why"]
    assert rig.doses() == []  # nothing is dosed until a person says so
    rig.set(6.6, 1400, T0 + 20)
    run(rig.dosing.approve, T0 + 20)
    assert rig.doses() == [("ph_down", "1")] and rig.dosing.suggestion is None
    row = rig.conn.execute("SELECT source, ph_before FROM chem_dose").fetchone()
    assert (row["source"], row["ph_before"]) == ("approved", 6.6)
    log = rig.conn.execute("SELECT product, amount, note FROM dose_log").fetchone()
    assert (log["product"], log["amount"]) == ("pH down", 1.0)  # shows on the charts too


def test_approval_rechecks_everything(rig):
    rig.dosing.set_mode("suggest", False, T0)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    rig.set(6.0, 1400, T0 + 400)  # back in range before the person tapped Approve
    with pytest.raises(Refused, match="back in range"):
        run(rig.dosing.approve, T0 + 400)
    assert rig.doses() == []
    with pytest.raises(Refused):
        run(rig.dosing.approve, T0 + 410)  # nothing left to approve


def test_dismiss_snoozes_that_suggestion_for_an_hour(rig):
    rig.dosing.set_mode("suggest", False, T0)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    rig.dosing.dismiss(T0 + 15)
    rig.set(6.6, 1400, T0 + 600)
    rig.tick(T0 + 600)
    assert rig.dosing.suggestion is None
    rig.set(6.6, 1400, T0 + 3700)
    rig.tick(T0 + 3700)
    assert rig.dosing.suggestion["kind"] == "ph_down"


# ---------------------------------------------------------------- auto mode
def test_auto_doses_once_then_waits_for_mixing(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    assert rig.doses() == [("ph_down", "1")]
    for t in (20, 300, 890):  # still too high, but the first dose has not mixed in yet
        rig.set(6.6, 1400, T0 + t)
        rig.tick(T0 + t)
    assert len(rig.doses()) == 1
    rig.set(6.45, 1400, T0 + 920)  # it worked a little: dose again
    rig.tick(T0 + 920)
    assert len(rig.doses()) == 2
    rig.set(6.1, 1400, T0 + 1900)
    rig.tick(T0 + 1900)
    assert len(rig.doses()) == 2  # in range: stop


def test_nutrients_are_a_then_b_in_equal_amounts(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.0, 800, T0 + 10)
    rig.tick(T0 + 10)
    assert rig.doses() == [("nutrient_a", "2")]
    rig.set(6.0, 800, T0 + 40)
    rig.tick(T0 + 40)
    assert len(rig.doses()) == 1  # B waits a full minute
    rig.set(6.0, 800, T0 + 71)
    rig.tick(T0 + 71)
    assert rig.doses() == [("nutrient_a", "2"), ("nutrient_b", "2")]


def test_nutrients_come_before_ph(rig):
    rig.dosing.set_mode("suggest", False, T0)
    rig.set(6.8, 700, T0 + 10)
    rig.tick(T0 + 10)
    assert rig.dosing.suggestion["kind"] == "nutrients"


def test_never_ph_up_within_an_hour_of_ph_down(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    rig.set(5.2, 1400, T0 + 1000)  # overshot: now too LOW
    rig.tick(T0 + 1000)
    assert rig.doses() == [("ph_down", "1")]  # no pH up yet
    rig.set(5.2, 1400, T0 + 3700)
    rig.tick(T0 + 3700)
    assert rig.doses()[-1] == ("ph_up", "1")


def test_no_response_after_two_doses_stops_dosing(rig):
    """Empty bottle or dead probe: the reading never moves."""
    rig.dosing.set_mode("auto", True, T0)
    for t in (10, 950, 1900, 2850, 3800):
        rig.set(6.6, 1400, T0 + t)
        rig.tick(T0 + t)
    assert len(rig.doses()) == 2
    assert "no effect" in rig.dosing.snapshot(T0 + 3800)["locked"]
    rig.dosing.unlock()
    rig.set(6.6, 1400, T0 + 4800)
    rig.tick(T0 + 4800)
    assert len(rig.doses()) == 3  # a person re-enabled it


def test_daily_cap_locks_out(rig):
    rig.dosing.set_mode("auto", True, T0)
    ph = 9.0
    t = 10
    for _ in range(25):
        rig.set(ph, 1400, T0 + t)
        rig.tick(T0 + t)
        ph -= 0.1  # each dose works, but there is a long way to go
        t += 950
    assert len(rig.doses()) == 20  # 20 x 1 mL = the daily 20 mL
    assert "daily limit" in rig.dosing.snapshot(T0 + t)["locked"]


def test_skipped_nutrient_b_locks_dosing(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.0, 800, T0 + 10)
    rig.tick(T0 + 10)
    rig.live.set_value("tent1/binary_sensor/leak", True, T0 + 30)
    run(rig.controller.tick, T0 + 30)  # leak alarm before B is due
    rig.set(6.0, 800, T0 + 75)
    rig.tick(T0 + 75)
    assert rig.doses() == [("nutrient_a", "2")]
    assert "uneven" in rig.dosing.snapshot(T0 + 75)["locked"]


# ---------------------------------------------------------------- refusing to act
@pytest.mark.parametrize(
    ("break_it", "reason"),
    [
        (lambda r: r.live.set_value("water/switch/rdwc_pump", False, T0 + 9), "circulation"),
        (
            lambda r: r.live.set_value("water/binary_sensor/res_low", True, T0 + 9),
            "reservoir is low",
        ),
        (lambda r: r.live.values.pop("water/binary_sensor/res_low"), "reservoir is low"),
        (lambda r: r.live.set_node_status("dosing", "offline", T0 + 9), "dosing node is offline"),
        (lambda r: r.live.set_node_status("water", "offline", T0 + 9), "water node is offline"),
        (lambda r: r.cal.clear(PH), "pH probe is not calibrated"),
        (lambda r: r.live.set_value(PH, None, T0 + 9, raw=1.0), "no fresh pH"),
        (lambda r: r.live.set_value("dosing/number/ph_down_ml_per_s", 0.0, T0 + 9), None),
    ],
)
def test_auto_refuses_when_anything_is_wrong(rig, break_it, reason):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.6, 1400, T0 + 8)
    break_it(rig)
    rig.tick(T0 + 10)
    assert rig.doses() == []
    if reason:
        assert reason in rig.dosing.snapshot(T0 + 10)["blocked"]


def test_overdue_calibration_blocks_dosing(rig):
    rig.dosing.set_mode("auto", True, T0)
    later = T0 + 31 * 86400
    rig.set(6.6, 1400, later)
    rig.tick(later)
    assert rig.doses() == [] and "days old" in rig.dosing.snapshot(later)["blocked"]


def test_stale_readings_are_not_acted_on(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.6, 1400, T0 + 10)
    for node in ("water", "dosing"):
        rig.live.set_node_status(node, "online", T0 + 200)
    rig.live.set_value("water/switch/rdwc_pump", True, T0 + 200)
    rig.tick(T0 + 200)  # the pH reading is now 190 s old
    assert rig.doses() == []


def test_a_sudden_jump_is_distrusted(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.set(6.0, 1400, T0 + 30)
    rig.feed(7.2, 1400, T0 + 50)  # probe bumped, or a bubble
    rig.tick(T0 + 50)
    assert rig.doses() == [] and "jumped" in rig.dosing.snapshot(T0 + 50)["blocked"]
    # If it is still there after the distrust period AND steady, it is real.
    for t in range(1000, 1200, 20):
        rig.set(7.2, 1400, T0 + t)
        rig.tick(T0 + t)
    assert rig.doses() == [("ph_down", "1")]


def test_unsteady_readings_are_not_acted_on(rig):
    rig.dosing.set_mode("auto", True, T0)
    for t, ph in ((10, 6.5), (30, 6.9), (50, 6.5), (70, 6.9)):
        rig.feed(ph, 1400, T0 + t)
        rig.tick(T0 + t)
    assert rig.doses() == [] and "unsteady" in rig.dosing.snapshot(T0 + 70)["blocked"]


def test_a_single_reading_is_never_acted_on(rig):
    """Right after the hub starts there is one reading: wait for more."""
    rig.dosing.set_mode("auto", True, T0)
    rig.feed(6.9, 1400, T0 + 10)
    rig.tick(T0 + 10)
    assert rig.doses() == [] and "collecting" in rig.dosing.snapshot(T0 + 10)["blocked"]


def test_leak_alarm_blocks_everything(rig):
    rig.dosing.set_mode("auto", True, T0)
    rig.live.set_value("dosing/binary_sensor/leak", True, T0 + 5)
    run(rig.controller.tick, T0 + 5)
    rig.set(6.6, 1400, T0 + 10)
    rig.tick(T0 + 10)
    assert rig.doses() == []
    with pytest.raises(Refused, match="leak"):
        run(rig.dosing.manual, "ph_down", T0 + 10)
    with pytest.raises(Refused, match="leak"):
        run(rig.dosing.prime, "ph_down", 10)


# ---------------------------------------------------------------- manual, priming, rates
def test_manual_dose_obeys_limits_without_needing_probes(rig):
    rig.set(6.0, 1400, T0 + 10)
    rig.cal.clear(PH)  # no probes at all: a person may still dose by hand
    run(rig.dosing.manual, "ph_down", T0 + 10)
    assert rig.doses() == [("ph_down", "1")]
    with pytest.raises(Refused, match="mix in"):
        run(rig.dosing.manual, "ph_down", T0 + 100)
    rig.set(6.0, 1400, T0 + 1000)
    with pytest.raises(Refused, match="less than an hour"):
        run(rig.dosing.manual, "ph_up", T0 + 1000)
    with pytest.raises(Refused):
        run(rig.dosing.manual, "bleach", T0 + 5000)
    rig.set(6.0, 1400, T0 + 5000)
    rig.live.set_value("water/switch/rdwc_pump", False, T0 + 5000)
    with pytest.raises(Refused, match="circulation"):
        run(rig.dosing.manual, "nutrients", T0 + 5000)


def test_prime_and_rate(rig):
    run(rig.dosing.prime, "nutrient_a", 20)
    assert rig.link.sent[-1] == ("growshed/dosing/prime/nutrient_a/command", "20")
    for pump, seconds in (("nutrient_a", 31), ("nutrient_a", 0), ("bleach", 10)):
        with pytest.raises(Refused):
            run(rig.dosing.prime, pump, seconds)
    run(rig.dosing.set_rate, "nutrient_a", 36.0, 30.0)
    assert rig.link.sent[-1] == ("growshed/dosing/number/nutrient_a_ml_per_s/command", "1.200")
    for ml, seconds in ((0, 30), (36, 0), (600, 30), (0.5, 30)):  # nothing, or implausible
        with pytest.raises(Refused):
            run(rig.dosing.set_rate, "nutrient_a", ml, seconds)


# ---------------------------------------------------------------- config limits
def test_config_cannot_exceed_the_node_limits(settings):
    base = load_config(settings.config_path).dosing.model_dump()
    for change in ({"max_dose_ml": 5}, {"max_day_ml": 50}, {"ph_dose_ml": 3}, {"wait_s": 60},
                   {"ph_low": 6.0, "ph_high": 6.1}, {"ph_low": 7, "ph_high": 6}):  # fmt: skip
        with pytest.raises(ValidationError):
            DosingConfig.model_validate({**base, **change})


# ---------------------------------------------------------------- through the API
def test_dosing_api(client):
    class Link:
        on_connect = None

        def __init__(self):
            self.sent = []

        async def publish(self, topic, payload, retain=False):
            self.sent.append((topic, payload))

    state = client.app.state
    link = Link()
    state.link = state.controller.link = state.dosing.link = link
    body = client.get("/api/control").json()["dosing"]
    assert body["mode"] == "off" and len(body["pumps"]) == 4 and body["suggestion"] is None

    # nothing is calibrated yet: no mode other than off
    no = client.post("/api/dosing/mode", json={"mode": "suggest"})
    assert no.status_code == 409 and "Calibrate first" in no.json()["detail"]

    assert (
        client.post(
            "/api/dosing/rate", json={"pump": "ph_down", "ml": 36, "seconds": 30}
        ).status_code
        == 200
    )
    assert link.sent[-1][1] == "1.200"
    assert (
        client.post("/api/dosing/prime", json={"pump": "ph_down", "seconds": 99}).status_code == 409
    )

    import time

    now = time.time()
    for pump in PUMPS:
        state.live.set_value(f"dosing/number/{pump}_ml_per_s", 1.2, now)
    state.calibrations.set_point(PH, "ph", 2.50, now, ref=7.0)
    state.calibrations.set_point(PH, "ph", 3.04, now, ref=4.0)
    state.calibrations.set_point(EC, "ec", 1.6, now, ref=1413)

    unconfirmed = client.post("/api/dosing/mode", json={"mode": "auto"})
    assert unconfirmed.status_code == 409 and "kill the plants" in unconfirmed.json()["detail"]
    assert client.get("/api/control").json()["dosing"]["mode"] == "off"
    ok = client.post("/api/dosing/mode", json={"mode": "auto", "acknowledged": True})
    assert ok.json()["dosing"]["mode"] == "auto"
    assert client.post("/api/dosing/mode", json={"mode": "suggest"}).json()["dosing"]["mode"] == (
        "suggest"
    )
    assert client.post("/api/dosing/approve").status_code == 409  # nothing suggested
    assert client.post("/api/dosing/dismiss").status_code == 200
    assert client.post("/api/dosing/unlock").status_code == 200
    assert client.post("/api/dosing/manual", json={"kind": "ph_down"}).status_code == 409
    # the generic "run a pump" endpoint must not reach the chemical pumps
    assert (
        client.post("/api/control/dose", json={"key": "dosing/switch/ph_down"}).status_code == 409
    )
