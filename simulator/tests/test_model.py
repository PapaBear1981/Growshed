from simulator.model import TentModel, WaterModel, approach, build_models


def run(model, seconds, hour, dt=30):
    for _ in range(int(seconds / dt)):
        model.step(dt, hour)


def payloads(model):
    return {entity: payload for _, entity, payload in model.entities()}


def test_approach_converges_without_overshoot():
    assert approach(10, 20, 0, 60) == 10
    assert 19.9 < approach(10, 20, 600, 60) <= 20


def test_tent_is_warmer_with_lights_on_than_off():
    day, night = TentModel(), TentModel()
    run(day, 4 * 3600, hour=12)
    run(night, 4 * 3600, hour=2)
    assert day.state["lights"] and not night.state["lights"]
    assert day.air_temp > night.air_temp + 3
    assert payloads(day)["light_lux"] != "0" and payloads(night)["light_lux"] == "0"


def test_exhaust_keeps_humidity_in_check():
    tent = TentModel()
    peak = 0.0
    for _ in range(8 * 120):
        tent.step(30, 12)
        peak = max(peak, tent.air_rh)
    assert 70 < peak < 75  # fan kicked in just past the 70 % threshold


def test_manual_command_overrides_schedule_until_fallback():
    tent = TentModel()
    assert tent.command("lights", True)
    tent.step(30, 2)  # 02:00, schedule says off
    assert tent.state["lights"] is True
    tent.fallback = True  # hub heartbeat lost: node reverts to its own schedule
    tent.step(30, 2)
    assert tent.state["lights"] is False
    assert not tent.command("nonexistent", True)


def test_tower_pump_stops_when_reservoir_low_or_leaking():
    tent = TentModel(has_tower=True)
    tent.command("tower_pump", True)
    tent.step(30, 12)
    assert tent.state["tower_pump"] is True
    tent.fault("tower_low on")
    tent.step(30, 12)
    assert tent.state["tower_pump"] is False
    tent.fault("tower_low off")
    tent.fault("leak on")
    tent.step(30, 12)
    assert tent.state["tower_pump"] is False


def test_water_heater_regulates_near_setpoint():
    water = WaterModel()
    run(water, 48 * 3600, hour=12, dt=60)
    assert 19.0 < water.res_temp < 21.0


def test_water_heater_off_when_reservoir_low_even_if_commanded():
    water = WaterModel()
    water.fault("drain")
    water.command("water_heater", True)
    water.step(30, 12)
    assert water.res_low and water.state["water_heater"] is False
    assert water.state["rdwc_pump"] is False and water.state["air_pump"] is True


def test_top_off_stops_at_full_and_on_leak():
    water = WaterModel()
    water.command("top_off", True)
    run(water, 3600, hour=12)
    assert water.res_high and water.state["top_off"] is False
    assert water.liters <= water.CAPACITY_L

    leaking = WaterModel()
    leaking.command("top_off", True)
    leaking.fault("leak on")
    leaking.step(30, 12)
    assert leaking.state["top_off"] is False and leaking.state["rdwc_pump"] is False


def test_sensor_failure_publishes_nan():
    tent = TentModel()
    assert tent.fault("sensor_fail on")
    tent.step(30, 12)
    assert payloads(tent)["air_temp"] == "nan"
    assert not tent.fault("gibberish")


def test_default_garden_has_three_tents_and_water():
    models = build_models()
    assert sorted(models) == ["tent1", "tent2", "tent3", "water"]
    assert "tower_pump" in models["tent3"].switches
