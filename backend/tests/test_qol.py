import io
import time
import zipfile

import anyio
import pytest

from growshed import backup, db, digest, maintenance, profiles, recorder
from growshed.config import load_config
from growshed.devicelog import DeviceLog, energy
from growshed.notify import Notification
from growshed.tunables import Tunables

T0 = 5_000_000.0
LIGHTS = "tent1/switch/lights"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "x.db")
    db.migrate(c)
    return c


@pytest.fixture
def site(settings):
    return load_config(settings.config_path)


# ---------------------------------------------------------------- tunables
def test_tunables_default_to_config_and_are_range_checked(conn, site):
    t = Tunables(conn, site)
    key = "alert.Tent too hot@tent1"
    assert t.get(key) == 30 and t.get("dosing.ph_high") == 6.2
    t.set(key, 28.5)
    assert t.get(key) == 28.5 and Tunables(conn, site).get(key) == 28.5  # survives restart
    assert t.get("alert.Tent too hot@tent2") == 30  # each tent has its own limit
    with pytest.raises(ValueError, match="between"):
        t.set(key, 80)
    with pytest.raises(ValueError):
        t.set("nonsense", 1)
    t.reset(key)
    assert t.get(key) == 30
    listed = {row["key"]: row for row in t.listing()}
    assert listed[key]["changed"] is False and listed[key]["kind"] == "temperature"
    assert "alert.Leak detected@tent1" not in listed  # on/off rules have no limit to tune


def test_dose_sizes_cannot_exceed_the_cap_and_ph_band_stays_wide(conn, site):
    t = Tunables(conn, site)
    with pytest.raises(ValueError):
        t.set("dosing.ph_dose_ml", 2.5)  # above the 2 mL cap
    t.set("dosing.ph_dose_ml", 1.5)
    with pytest.raises(ValueError, match="0.4"):
        t.set("dosing.ph_low", 6.0)  # only 0.2 below ph_high
    with pytest.raises(ValueError, match="0.4"):
        t.set("dosing.ph_high", 5.8)
    t.set("dosing.ph_high", 6.5)
    t.set("dosing.ph_low", 6.0)


def test_alerts_dosing_and_watering_follow_the_tunables(client):
    state = client.app.state
    now = state.alerts.started_at
    state.live.set_node_status("tent1", "online", now)
    state.live.set_value("tent1/sensor/air_temp", 28.0, now)
    state.alerts.tick(now)
    state.live.set_value("tent1/sensor/air_temp", 28.0, now + 130)
    state.live.touch_node("tent1", now + 130)
    assert not [n for n in state.alerts.tick(now + 130) if "too hot" in n.title]
    res = client.put("/api/tunables", json={"key": "alert.Tent too hot@tent1", "value": 27})
    assert res.status_code == 200
    state.live.set_value("tent1/sensor/air_temp", 28.0, now + 140)
    state.alerts.tick(now + 140)
    state.live.set_value("tent1/sensor/air_temp", 28.0, now + 270)
    state.live.touch_node("tent1", now + 270)
    hot = [n for n in state.alerts.tick(now + 270) if "too hot" in n.title]
    assert hot and "limit 80.6 °F" in hot[0].body

    client.put("/api/tunables", json={"key": "dosing.ph_high", "value": 6.5})
    assert state.dosing.target("ph_high") == 6.5
    assert client.get("/api/control").json()["dosing"]["targets"]["ph_high"] == 6.5
    key = "watering.below@tent2/sensor/soil_1"
    client.put("/api/tunables", json={"key": key, "value": 40})
    assert client.get("/api/control").json()["watering"][0]["below"] == 40
    bad = client.put("/api/tunables", json={"key": "dosing.ph_dose_ml", "value": 9})
    assert bad.status_code == 409 and "between" in bad.json()["detail"]
    assert client.delete("/api/tunables", params={"key": key}).status_code == 200
    assert client.get("/api/control").json()["watering"][0]["below"] == 35


# ---------------------------------------------------------------- crop profiles
def test_crop_profile_sets_one_zone_only(conn, site):
    t = Tunables(conn, site)
    changed = profiles.apply_profile(t, site, "tent3", "Strawberries")
    assert changed >= 4
    assert t.get("alert.Tent too hot@tent3") == 27 and t.get("alert.Tent too hot@tent1") == 30
    assert t.get("alert.Water too warm@tower") == 22  # the tower inside that tent, too
    assert t.get("dosing.ph_high") == 6.2  # the RDWC reservoir is a different zone: untouched
    profiles.apply_profile(t, site, "rdwc", "Strawberries")
    assert (t.get("dosing.ph_low"), t.get("dosing.ph_high"), t.get("dosing.ec_low")) == (
        5.6, 6.1, 1000,
    )  # fmt: skip
    assert profiles.current_profiles(t, site)["tent3"] == "Strawberries"
    with pytest.raises(ValueError):
        profiles.apply_profile(t, site, "tent3", "Bananas")


def test_every_profile_is_within_the_allowed_ranges(conn, site):
    for name in profiles.PROFILES:
        t = Tunables(conn, site)
        for zone in ("tent1", "tent3", "rdwc"):
            profiles.apply_profile(t, site, zone, name)  # raises if any value is out of range


# ---------------------------------------------------------------- device history, energy
def test_device_log_intervals_and_energy(conn, site):
    log = DeviceLog(conn, {LIGHTS})
    log.record(LIGHTS, True, 1000)
    log.record(LIGHTS, True, 1500)  # no change: not stored again
    log.record(LIGHTS, False, 4600)
    log.record(LIGHTS, True, 8000)
    log.record("tent9/switch/x", True, 1000)  # not a configured device
    log.record(LIGHTS, None, 9000)  # unknown state is not a change
    assert conn.execute("SELECT COUNT(*) FROM state_change").fetchone()[0] == 3
    assert log.intervals(LIGHTS, 0, 10000) == [(1000, 4600), (8000, 10000)]
    assert log.intervals(LIGHTS, 2000, 3000) == [(2000, 3000)]  # already on at the start
    assert log.intervals(LIGHTS, 5000, 6000) == []
    assert log.on_seconds(LIGHTS, 0, 10000) == 5600
    assert DeviceLog(conn, {LIGHTS})._last[LIGHTS] is True  # remembered across restarts

    device = next(d for d in site.devices if d.state_key == LIGHTS)
    result = energy(log, [device], lambda key: 400.0, 0.20, 1000, 4600)
    assert result["devices"][0]["hours_on"] == 1.0
    assert result["kwh"] == 0.4 and result["cost"] == 0.08


def test_device_history_and_energy_api(client):
    state = client.app.state
    now = time.time()
    anyio.run(state.ingest.handle, "growshed/tent1/switch/lights/state", "ON", now - 7200)
    anyio.run(state.ingest.handle, "growshed/tent1/switch/lights/state", "OFF", now - 3600)
    body = client.get(
        "/api/device_history", params={"keys": LIGHTS, "start": now - 86400, "end": now}
    ).json()
    assert body[LIGHTS] == [[int(now - 7200), int(now - 3600)]]
    client.put("/api/tunables", json={"key": f"watts@{LIGHTS}", "value": 480})
    power = client.get("/api/energy", params={"days": 1}).json()
    lights = next(d for d in power["devices"] if d["key"] == LIGHTS)
    assert lights["hours_on"] == 1.0 and lights["kwh"] == 0.48 and power["cost"] == 0.07


# ---------------------------------------------------------------- reminders and bottles
def test_reminders_api_and_alert(client):
    rows = client.get("/api/reminders").json()
    assert len(rows) == 5 and not any(r["overdue"] for r in rows)
    added = client.post("/api/reminders", json={"name": "Calibrate pumps", "every_days": 60}).json()
    new = next(r for r in added if r["name"] == "Calibrate pumps")
    conn = client.app.state.db
    conn.execute("UPDATE reminder SET last_done_at = ? WHERE id = ?", (1000, new["id"]))
    conn.commit()
    assert client.get("/api/reminders").json()[0]["name"] == "Calibrate pumps"  # most overdue first
    engine = client.app.state.alerts
    notes = engine.tick(time.time())
    assert [n.body for n in notes if n.title == "Warning: Maintenance due"] == [
        "Reminders: Calibrate pumps"
    ]
    done = client.post(f"/api/reminders/{new['id']}/done").json()
    assert not next(r for r in done if r["id"] == new["id"])["overdue"]
    assert client.post("/api/reminders/999/done").status_code == 404
    assert len(client.delete(f"/api/reminders/{new['id']}").json()) == 5
    assert client.post("/api/reminders", json={"name": "", "every_days": 0}).status_code == 422


def test_bottle_levels_follow_the_doses(conn):
    pumps = {"ph_down": "pH down", "ph_up": "pH up"}
    assert maintenance.bottles(conn, pumps)[0]["left_ml"] is None  # not set up yet
    maintenance.refill_bottle(conn, "ph_down", 500, T0)
    sql = (
        "INSERT INTO chem_dose (ts, kind, pump, ml, source) "
        "VALUES (?, 'ph_down', 'ph_down', ?, 'auto')"
    )
    conn.execute(sql, (T0 - 10, 99))  # before the refill: not counted
    conn.execute(sql, (T0 + 10, 430))
    conn.commit()
    bottle = maintenance.bottles(conn, pumps)[0]
    assert bottle["left_ml"] == 70 and bottle["low"] is True  # under 15 %
    maintenance.refill_bottle(conn, "ph_down", 500, T0 + 20)
    assert maintenance.bottles(conn, pumps)[0]["left_ml"] == 500


def test_bottle_api(client):
    assert (
        client.post("/api/bottles", json={"pump": "bleach", "capacity_ml": 500}).status_code == 422
    )
    rows = client.post("/api/bottles", json={"pump": "ph_up", "capacity_ml": 250}).json()
    assert next(r for r in rows if r["pump"] == "ph_up")["left_ml"] == 250


# ---------------------------------------------------------------- backups
def test_backup_snapshot_prune_and_export(conn, tmp_path, settings):
    db.set_setting(conn, "display_units", "metric")
    folder = tmp_path / "backups"
    for i in range(17):
        backup.run_backup(conn, folder, settings.config_path, T0 + i * 86400)
    names = [b["name"] for b in backup.list_backups(folder)]
    assert len(names) == 14 and names[0] > names[-1]  # newest first, oldest pruned
    assert len(list(folder.glob("config-*.yaml"))) == 14
    copy = db.connect(folder / names[0])
    assert db.get_setting(copy, "display_units", "x") == "metric"  # a real, readable database

    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "1-abc.jpg").write_bytes(b"\xff\xd8\xff")
    archive = backup.export_zip(conn, settings.config_path, photos)
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["config.yaml", "growshed.db", "photos/1-abc.jpg"]
    assert backup.list_backups(tmp_path / "nowhere") == []


def test_backup_api(client):
    assert client.get("/api/backups").json() == []
    assert len(client.post("/api/backups/run").json()) == 1
    res = client.get("/api/backups/export")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert "growshed.db" in zf.namelist() and "config.yaml" in zf.namelist()


# ---------------------------------------------------------------- quiet hours, summary
def at(hour, minute=0):
    """A UTC timestamp at this time of day."""
    return 1_700_000_000 // 86400 * 86400 + hour * 3600 + minute * 60


def test_quiet_hours_hold_warnings_but_never_critical(conn):
    digest.set_preference(conn, "quiet_enabled", "1")  # 22:00-07:00 UTC by default
    courier = digest.Courier(conn)
    warning = Notification("Warning: Tent too hot", "Tent 1", 3)
    critical = Notification("CRITICAL: Leak detected", "Tent 1", 5)
    assert courier.route(warning, at(23)) == []
    assert courier.route(critical, at(23)) == [critical]  # leaks always go out at once
    assert courier.route(warning, at(3)) == []
    assert courier.release(at(6, 59)) == []  # still quiet
    morning = courier.release(at(7, 1))
    assert len(morning) == 1 and morning[0].title == "2 alerts during quiet hours"
    assert "Tent too hot" in morning[0].body
    assert courier.release(at(7, 2)) == []  # delivered once
    assert courier.route(warning, at(12)) == [warning]  # daytime: straight through


def test_quiet_hours_off_by_default_and_follow_the_time_zone(conn):
    courier = digest.Courier(conn)
    warning = Notification("w", "b", 3)
    assert courier.route(warning, at(23)) == [warning]
    digest.set_preference(conn, "quiet_enabled", "1")
    digest.set_preference(conn, "timezone", "America/New_York")
    prefs = digest.preferences(conn)
    assert digest.in_quiet_hours(prefs, at(4))  # 23:00 or midnight in New York
    assert not digest.in_quiet_hours(prefs, at(20))  # mid-afternoon there


def test_preferences_are_validated(conn):
    for key, value in (("timezone", "Mars/Olympus"), ("quiet_start", "2500"),
                       ("quiet_enabled", "yes"), ("volume", "11")):  # fmt: skip
        with pytest.raises(ValueError):
            digest.set_preference(conn, key, value)
    assert digest.preferences(conn)["summary_minute"] == "480"


def test_summary_is_due_once_a_day_after_the_chosen_time(conn):
    courier = digest.Courier(conn)
    assert not courier.summary_due(at(7, 59))
    assert courier.summary_due(at(8, 0))
    assert not courier.summary_due(at(9))
    assert courier.summary_due(at(8, 5) + 86400)
    digest.set_preference(conn, "summary_enabled", "0")
    assert not courier.summary_due(at(8, 5) + 2 * 86400)


def test_summary_text(client):
    state = client.app.state
    now = time.time()
    for ts, value in ((now - 7200, 20.0), (now - 3600, 25.0)):
        state.recorder.add("tent1/sensor/air_temp", value, ts)
    state.recorder.flush()
    note = digest.build_summary(state, now)
    assert note.title.startswith("Growshed daily summary")
    assert "Tent 1 air temperature: 68.0 °F to 77.0 °F" in note.body
    assert "Active alerts: 0" in note.body


def test_preferences_api(client):
    assert client.get("/api/preferences").json()["timezone"] == "UTC"
    ok = client.put("/api/preferences", json={"key": "timezone", "value": "America/Chicago"})
    assert ok.json()["timezone"] == "America/Chicago"
    bad = client.put("/api/preferences", json={"key": "timezone", "value": "Nowhere"})
    assert bad.status_code == 409


# ---------------------------------------------------------------- statistics and grows
def test_stats_span_raw_and_summarised_data(conn):
    rec = recorder.Recorder(conn, {"k"}, min_interval_s=0)
    day = 86400 * 200
    for i in range(0, 4 * 3600, 60):
        rec.add("k", 10.0 if i < 2 * 3600 else 30.0, day + i)
    rec.flush()
    rec.rollup(day + 3 * 3600)  # part hourly, part 5-minute, the rest still raw
    s = recorder.stats(conn, "k", day, day + 4 * 3600)
    assert (s["min"], s["max"], s["avg"], s["n"]) == (10.0, 30.0, 20.0, 240)
    assert recorder.stats(conn, "k", day + 10**7, day + 10**7 + 60) is None
    assert recorder.stats(conn, "unknown", 0, 10) is None


def test_grow_lifecycle_and_frozen_summary(client):
    state = client.app.state
    now = time.time()
    start = now - 3 * 86400
    assert client.post("/api/grows", json={"name": "x", "zone": "attic"}).status_code == 422
    grow_id = client.post(
        "/api/grows",
        json={"name": "Winter lettuce", "zone": "tent1", "crop": "Lettuce", "started_at": start},
    ).json()["id"]
    plant_id = client.post(
        "/api/plants", json={"zone": "tent1", "name": "Butterhead", "started_at": start}
    ).json()["id"]
    state.db.execute("UPDATE plant SET grow_id = ? WHERE id = ?", (grow_id, plant_id))
    for ts, value in ((start + 100, 18.0), (start + 200, 26.0)):
        state.recorder.add("tent1/sensor/air_temp", value, ts)
        state.recorder.add("tent2/sensor/air_temp", 99.0, ts)  # another tent: not this grow
    state.recorder.flush()
    anyio.run(state.ingest.handle, "growshed/tent1/switch/lights/state", "ON", start + 3600)
    anyio.run(state.ingest.handle, "growshed/tent1/switch/lights/state", "OFF", start + 7200)
    client.put("/api/tunables", json={"key": f"watts@{LIGHTS}", "value": 500})
    client.post("/api/doses", json={"zone": "rdwc", "product": "pH down", "amount": 3})

    live = client.get(f"/api/grows/{grow_id}").json()
    summary = live["summary"]
    temp = next(s for s in summary["sensors"] if s["key"] == "tent1/sensor/air_temp")
    assert (temp["min"], temp["avg"], temp["max"]) == (18.0, 22.0, 26.0)
    assert not [s for s in summary["sensors"] if s["key"].startswith("tent2/")]
    assert summary["days"] == 3 and summary["energy_kwh"] == 0.5
    assert summary["additions"] == [{"product": "pH down", "unit": "mL", "total": 3.0, "times": 1}]
    assert summary["plants"][0]["name"] == "Butterhead"

    ended = client.post(
        f"/api/grows/{grow_id}/status", json={"action": "end", "yield_g": 640, "notes": "Good"}
    ).json()
    assert ended["ended_at"] and ended["yield_g"] == 640 and ended["notes"] == "Good"
    assert client.get("/api/plants").json()[0]["ended_at"]  # its plants finish with it
    # New data afterwards does not change the finished grow's record.
    state.recorder.add("tent1/sensor/air_temp", 40.0, start + 300)
    state.recorder.flush()
    frozen = client.get(f"/api/grows/{grow_id}").json()["summary"]
    assert (
        next(s for s in frozen["sensors"] if s["key"].endswith("tent1/sensor/air_temp"))["max"]
        == 26.0
    )

    listed = client.get("/api/grows").json()
    assert listed[0]["name"] == "Winter lettuce" and "sensors" in listed[0]["summary"]
    reopened = client.post(f"/api/grows/{grow_id}/status", json={"action": "reopen"}).json()
    assert reopened["ended_at"] is None
    assert client.get("/api/grows/999").status_code == 404
    edit = {"name": "Winter lettuce 1", "zone": "tent1", "yield_g": 700}
    assert client.put(f"/api/grows/{grow_id}", json=edit).json() == {"ok": True}
    assert client.get(f"/api/grows/{grow_id}").json()["yield_g"] == 700
