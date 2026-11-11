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


def test_light_schedule_follows_the_settings_and_is_clamped():
    tent = TentModel()
    assert tent.set_number("light_on_minute", 60) and tent.set_number("light_off_minute", 180)
    tent.step(30, 2)  # 02:00 is inside 01:00-03:00
    assert tent.state["lights"] and tent.source["lights"] == "auto"
    tent.step(30, 12)
    assert not tent.state["lights"]
    tent.set_number("max_temp", 99)
    assert tent.numbers["max_temp"] == 30  # clamped like the firmware
    assert not tent.set_number("nonsense", 1)
    assert payloads(tent)["light_on_minute"] == "60"


def test_exhaust_keeps_humidity_in_check():
    tent = TentModel()
    peak = 0.0
    for _ in range(8 * 120):
        tent.step(30, 12)
        peak = max(peak, tent.air_rh)
    assert 70 < peak < 75  # fan kicked in just past the 70 % limit


def test_manual_mode_until_fallback():
    tent = TentModel()
    assert tent.set_mode("lights", "on")
    tent.step(30, 2)  # 02:00, schedule says off
    assert tent.state["lights"] and tent.source["lights"] == "manual"
    assert payloads(tent)["lights_mode"] == "on"
    tent.fallback = True  # hub heartbeat lost: the node reverts to its own schedule
    tent.step(30, 2)
    assert not tent.state["lights"] and tent.source["lights"] == "fallback"
    assert not tent.set_mode("nonexistent", "on") and not tent.set_mode("lights", "maybe")


def test_overtemperature_cuts_the_lights_even_in_manual_on():
    tent = TentModel()
    tent.set_mode("lights", "on")
    tent.air_temp = 36.5
    tent.step(60, 12)
    assert tent.state["lights"]  # not yet: must hold for two minutes
    tent.air_temp = 36.5
    tent.step(90, 12)
    assert not tent.state["lights"] and tent.source["lights"] == "interlock"
    assert tent.last_interlock == "I-4 lights"
    assert tent.state["exhaust_fan"] and tent.source["exhaust_fan"] in ("auto", "interlock")


def test_exhaust_forced_on_when_hot_or_sensor_dead():
    tent = TentModel()
    tent.set_mode("exhaust_fan", "off")
    tent.air_temp = 31.0
    tent.step(1, 12)
    assert tent.state["exhaust_fan"] and tent.last_interlock == "I-5 exhaust_fan"

    blind = TentModel()
    blind.set_mode("exhaust_fan", "off")
    blind.fault("sensor_fail on")
    blind.step(60, 12)
    assert not blind.state["exhaust_fan"]
    blind.step(90, 12)
    assert blind.state["exhaust_fan"] and blind.source["exhaust_fan"] == "interlock"
    assert payloads(blind)["air_temp"] == "nan"


def test_tower_pump_stops_when_reservoir_low_or_leaking():
    tent = TentModel(has_tower=True)
    tent.set_mode("tower_pump", "on")
    tent.step(30, 12)
    assert tent.state["tower_pump"]
    tent.fault("tower_low on")
    tent.step(30, 12)
    assert not tent.state["tower_pump"] and tent.last_interlock == "I-7 tower_pump"
    tent.fault("tower_low off")
    tent.hub_leak = True  # a leak somewhere else in the house
    tent.step(30, 12)
    assert not tent.state["tower_pump"] and tent.last_interlock == "I-10 tower_pump"


def test_water_heater_regulates_near_setpoint():
    water = WaterModel()
    run(water, 48 * 3600, hour=12, dt=60)
    assert 19.0 < water.res_temp < 21.0
    water.set_number("water_setpoint", 22)
    run(water, 48 * 3600, hour=12, dt=60)
    assert 21.0 < water.res_temp < 23.0


def test_water_heater_off_when_reservoir_low_even_if_commanded():
    water = WaterModel()
    water.fault("drain")
    water.set_mode("water_heater", "on")
    water.step(30, 12)
    assert water.res_low and not water.state["water_heater"]
    assert water.source["water_heater"] == "interlock"
    assert not water.state["rdwc_pump"] and water.state["air_pump"]


def test_top_off_is_dose_only_and_stops_at_full_and_on_leak():
    water = WaterModel()
    water.step(30, 12)
    assert not water.state["top_off"] and water.source["top_off"] == "idle"
    before = water.liters
    assert water.request_dose("top_off", 9999)
    run(water, 600, hour=12, dt=1)
    assert 3.9 < water.liters - before < 4.1  # capped at 120 s = 4 L
    assert not water.state["top_off"]

    full = WaterModel()
    full.liters = full.HIGH_L
    full.request_dose("top_off", 60)
    full.step(1, 12)
    assert not full.state["top_off"] and full.source["top_off"] == "refused"
    assert full.last_interlock == "I-9 top_off"

    leaking = WaterModel()
    leaking.fault("leak on")
    leaking.request_dose("top_off", 60)
    leaking.step(1, 12)
    assert (
        not leaking.state["top_off"]
        and not leaking.state["rdwc_pump"]
        and leaking.state["air_pump"]
    )


def test_chemistry_probes_report_volts_and_follow_buffers():
    water = WaterModel()
    water.step(1, 12)
    in_reservoir = float(payloads(water)["ph"])
    assert water.fault("ph_buffer 4")
    acid = float(payloads(water)["ph"])
    assert water.fault("ph_buffer 10")
    alkaline = float(payloads(water)["ph"])
    assert acid > in_reservoir > alkaline  # lower pH = higher volts on cheap boards
    assert water.fault("ph_buffer off")
    weak = float(payloads(water)["ec"])
    assert water.fault("ec_solution 2500")
    assert float(payloads(water)["ec"]) > weak
    assert (
        water.fault("ec_solution off") and water.fault("ph_set 7.5") and water.fault("ec_set 400")
    )
    assert water.ph == 7.5 and water.ec == 400
    assert not water.fault("ph_buffer banana")


def test_chemistry_drifts_slowly():
    water = WaterModel()
    ph, ec = water.ph, water.ec
    run(water, 5 * 86400, hour=12, dt=600)
    assert ph < water.ph < ph + 1 and ec - 300 < water.ec < ec


def test_sensor_failure_publishes_nan():
    tent = TentModel()
    assert tent.fault("sensor_fail on")
    tent.step(30, 12)
    assert payloads(tent)["air_temp"] == "nan"
    assert not tent.fault("gibberish")


def test_soil_pots_dry_out_and_report_volts():
    tent = TentModel(soil_pots=2)
    start = list(tent.soil)
    run(tent, 24 * 3600, hour=12, dt=600)
    assert all(0 < now < before for now, before in zip(tent.soil, start, strict=True))
    volts = float(payloads(tent)["soil_1"])
    assert TentModel.SOIL_WET_V < volts < TentModel.SOIL_DRY_V
    assert tent.fault("soil_dry")
    drier = float(payloads(tent)["soil_1"])
    assert drier > volts  # drier soil = higher voltage
    assert not TentModel().fault("soil_dry")  # a tent without pots has no such fault


def test_watering_dose_wets_the_pot_within_hard_limits():
    tent = TentModel(soil_pots=1)
    before = tent.soil[0]
    assert tent.request_dose("water_1", 60)  # asks for far too long
    run(tent, 120, hour=12, dt=1)
    gained = tent.soil[0] - before
    assert 0.39 < gained < 0.41  # 20 s at most (I-11)
    assert tent.request_dose("water_1", 5)
    tent.step(1, 12)
    assert tent.source["water_1"] == "refused"  # must rest 10 minutes
    assert not tent.request_dose("water_9", 5)


def test_watering_refused_on_leak_tank_low_and_fallback():
    for setup, rule in (
        (lambda t: t.fault("leak on"), "I-10"),
        (lambda t: t.fault("tank_low on"), "I-12"),
        (lambda t: setattr(t, "fallback", True), "fallback"),
    ):
        tent = TentModel(soil_pots=1)
        setup(tent)
        tent.request_dose("water_1", 10)
        tent.step(1, 12)
        assert not tent.state["water_1"] and tent.last_interlock == f"{rule} water_1"


def test_unplugged_soil_sensor_reads_dry_whatever_the_pump_does():
    tent = TentModel(soil_pots=2)
    assert tent.fault("soil_unplug")
    tent.request_dose("water_1", 10)
    run(tent, 30, hour=12, dt=1)
    assert float(payloads(tent)["soil_1"]) > 2.55  # still "bone dry"


def test_default_garden_has_three_tents_and_water():
    models = build_models()
    assert sorted(models) == ["tent1", "tent2", "tent3", "water"]
    assert "tower_pump" in models["tent3"].devices
    assert len(models["tent2"].soil) == 4 and models["tent1"].soil == []
    assert "water_4" in models["tent2"].dosers and "top_off" in models["water"].dosers
