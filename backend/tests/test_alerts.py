import pytest

from growshed import db
from growshed.alerts import AlertEngine
from growshed.config import load_config
from growshed.state import LiveState

LEAK = "tent1/binary_sensor/leak"
TEMP = "tent1/sensor/air_temp"
T0 = 1_000_000.0


@pytest.fixture
def site(settings):
    return load_config(settings.config_path)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "x.db")
    db.migrate(c)
    return c


@pytest.fixture
def live():
    state = LiveState()
    for node in ("tent1", "tent2", "tent3", "water"):
        state.set_node_status(node, "online", T0)
    return state


@pytest.fixture
def engine(conn, site, live):
    return AlertEngine(conn, site, live, started_at=T0)


def alive(live, now, nodes=("tent1", "tent2", "tent3", "water")):
    for node in nodes:
        live.touch_node(node, now)


def titles(notes):
    return [n.title for n in notes]


def leak_titles(notes):
    return [n.title for n in notes if "Leak" in n.title]


def test_leak_raises_immediately_as_critical(engine, live):
    live.set_value(LEAK, False, T0)
    assert engine.tick(T0 + 1) == []
    live.set_value(LEAK, True, T0 + 2)
    notes = engine.tick(T0 + 3)
    assert titles(notes) == ["CRITICAL: Leak detected"]
    assert notes[0].body == "Tent 1 · Floor leak" and notes[0].priority == 5
    active = engine.active()
    assert len(active) == 1 and active[0]["severity"] == "critical" and engine.changed


def test_leak_repeats_until_acknowledged(engine, live):
    live.set_value(LEAK, True, T0)
    engine.tick(T0)
    alive(live, T0 + 100)
    assert engine.tick(T0 + 100) == []
    alive(live, T0 + 301)
    assert titles(engine.tick(T0 + 301)) == ["Still active: Leak detected"]
    assert engine.ack(engine.active()[0]["id"], T0 + 310)
    alive(live, T0 + 700)
    assert leak_titles(engine.tick(T0 + 700)) == []  # acknowledged: no more repeats
    leak = next(a for a in engine.active() if a["name"] == "Leak detected")
    assert leak["acked_at"] == T0 + 310  # ...but still active
    assert not engine.ack(99999, T0)


def test_alert_clears_only_after_staying_good(engine, live):
    live.set_value(LEAK, True, T0)
    engine.tick(T0)
    live.set_value(LEAK, False, T0 + 10)
    assert engine.tick(T0 + 20) == [] and engine.active()
    live.set_value(LEAK, True, T0 + 30)  # wet again before the clear delay: stays active
    engine.tick(T0 + 40)
    live.set_value(LEAK, False, T0 + 50)
    engine.tick(T0 + 60)
    assert engine.active()
    alive(live, T0 + 121)
    assert titles(engine.tick(T0 + 121)) == ["Resolved: Leak detected"]
    assert engine.active() == []
    event = engine.recent()[0]
    assert event["ended_at"] == T0 + 121 and event["started_at"] == T0


def test_leak_alert_survives_its_node_going_offline(engine, live):
    live.set_value(LEAK, True, T0)
    engine.tick(T0)
    live.set_node_status("tent1", "offline", T0 + 5)
    live.set_value(LEAK, False, T0 + 5)  # even a stale "dry" must not clear it
    for t in (T0 + 100, T0 + 200):
        engine.tick(t)
    assert [a["name"] for a in engine.active()] == ["Leak detected"]


def test_binary_state_from_dead_node_never_raises(engine, live):
    live.set_node_status("tent1", "offline", T0)
    live.set_value(LEAK, True, T0)
    live.nodes["tent1"]["status"] = "offline"
    assert engine.tick(T0 + 1) == []


def test_threshold_needs_to_hold_for_the_whole_delay(engine, live):
    live.set_value(TEMP, 31.0, T0)
    assert engine.tick(T0) == []
    live.set_value(TEMP, 29.0, T0 + 60)  # dipped back: timer restarts
    engine.tick(T0 + 60)
    live.set_value(TEMP, 31.0, T0 + 90)
    engine.tick(T0 + 90)
    live.set_value(TEMP, 31.5, T0 + 200)
    assert engine.tick(T0 + 200) == []  # only 110 s of the required 120
    live.set_value(TEMP, 31.5, T0 + 215)
    notes = engine.tick(T0 + 215)
    assert titles(notes) == ["Warning: Tent too hot"]
    assert notes[0].body == "Tent 1 · Air temperature: 88.7 °F (limit 86.0 °F)"
    assert notes[0].priority == 3


def test_notification_units_follow_the_display_setting(conn, site, live):
    engine = AlertEngine(conn, site, live, started_at=T0, get_units=lambda: "metric")
    live.set_value(TEMP, 10.0, T0)
    engine.tick(T0)
    live.set_value(TEMP, 10.0, T0 + 121)
    assert engine.tick(T0 + 121)[0].body == "Tent 1 · Air temperature: 10.0 °C (limit 15.0 °C)"


def test_failed_reading_is_unknown_not_an_alert(engine, live):
    live.set_value(TEMP, None, T0)  # "nan" from the node
    for t in (T0, T0 + 200):
        assert engine.tick(t) == []


def test_stale_sensor_alert_but_not_when_whole_node_is_down(engine, live):
    live.set_value(TEMP, 22.0, T0)
    alive(live, T0 + 590)
    assert engine.tick(T0 + 590) == []
    alive(live, T0 + 601)  # node still talking, this sensor silent for > 10 min
    notes = engine.tick(T0 + 601)
    assert "Warning: Sensor not reporting" in titles(notes)
    assert any(n.body == "Tent 1 · Air temperature" for n in notes)


def test_node_offline_alert_after_delay_only_for_seen_nodes(conn, site):
    live = LiveState()  # nothing has ever been heard from
    engine = AlertEngine(conn, site, live, started_at=T0)
    assert engine.tick(T0 + 10_000) == []  # never-seen nodes do not alert (still being built)
    live.set_node_status("water", "online", T0 + 10_000)
    live.set_node_status("water", "offline", T0 + 10_010)
    assert engine.tick(T0 + 10_020) == []
    notes = engine.tick(T0 + 10_320)
    assert titles(notes) == ["Warning: Node offline"] and notes[0].body == "Water node"


def test_silent_node_counts_as_offline(engine, live):
    engine.tick(T0 + 121)  # quiet for > 120 s: starts the offline timer
    notes = engine.tick(T0 + 121 + 300)
    assert titles(notes).count("Warning: Node offline") == 4


def test_fallback_mode_alert(engine, live):
    live.set_value("tent2/text_sensor/mode", "fallback", T0)
    engine.tick(T0)
    alive(live, T0 + 61)
    assert titles(engine.tick(T0 + 61)) == ["Warning: Node lost contact with the hub"]


def test_restart_keeps_active_alerts_without_renotifying(conn, site, live):
    first = AlertEngine(conn, site, live, started_at=T0)
    live.set_value(LEAK, True, T0)
    first.tick(T0)
    event_id = first.active()[0]["id"]
    first.ack(event_id, T0 + 5)

    second = AlertEngine(conn, site, live, started_at=T0 + 50)
    assert [a["id"] for a in second.active()] == [event_id]
    assert second.active()[0]["acked_at"] == T0 + 5
    alive(live, T0 + 60)
    assert second.tick(T0 + 60) == []
    assert len(second.recent()) == 1


def test_restart_closes_alerts_whose_rule_was_removed(conn, site, live):
    conn.execute(
        "INSERT INTO alert_event (key, name, subject, severity, detail, started_at) "
        "VALUES ('rule:Gone:x', 'Gone', 'x', 'warning', '', 1)"
    )
    conn.commit()
    engine = AlertEngine(conn, site, live, started_at=T0)
    assert engine.active() == [] and engine.recent()[0]["ended_at"] == T0


def test_rules_cover_every_tent_and_both_water_zones(engine):
    keys = set(engine.conditions)
    for tent in ("tent1", "tent2", "tent3"):
        assert f"rule:Leak detected:{tent}/binary_sensor/leak" in keys
        assert f"rule:Tent too hot:{tent}/sensor/air_temp" in keys
    assert "rule:Water too cold:tent3/sensor/tower_temp" in keys
    assert "rule:Water too cold:water/sensor/res_temp" in keys
    assert "rule:Tent too hot:water/sensor/room_temp" not in keys
    assert "rule:Basement humidity high:water/sensor/room_rh" in keys
