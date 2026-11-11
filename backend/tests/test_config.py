import pytest
from pydantic import ValidationError

from growshed.config import Settings, SiteConfig, load_config

BASE = {
    "zones": [{"id": "tent1", "name": "Tent 1", "kind": "tent"}],
    "nodes": [{"id": "tent1", "name": "Tent 1 node"}],
}


def sensor(**over):
    return {
        "node": "tent1",
        "key": "air_temp",
        "zone": "tent1",
        "kind": "temperature",
        "name": "Air",
        **over,
    }


def test_repo_config_loads(settings):
    site = load_config(settings.config_path)
    assert {z.id for z in site.zones} >= {"tent1", "tent2", "tent3", "tower", "rdwc", "room"}
    assert {n.id for n in site.nodes} == {"tent1", "tent2", "tent3", "water", "dosing"}
    tower_pump = next(d for d in site.devices if d.key == "tower_pump")
    assert tower_pump.node == "tent3"  # the tower is run by its own tent's node


def test_state_keys():
    site = SiteConfig.model_validate(
        {**BASE, "sensors": [sensor(key="leak", component="binary_sensor", kind="leak")]}
    )
    assert site.sensors[0].state_key == "tent1/binary_sensor/leak"


@pytest.mark.parametrize(
    "bad",
    [
        {**BASE, "sensors": [sensor(zone="nope")]},
        {**BASE, "sensors": [sensor(node="nope")]},
        {**BASE, "sensors": [sensor(), sensor()]},
        {**BASE, "zones": BASE["zones"] * 2},
        {**BASE, "zones": [{"id": "t", "name": "T", "kind": "tent", "parent": "nope"}]},
        {**BASE, "zones": [{"id": "t", "name": "T", "kind": "spaceship"}]},
    ],
)
def test_invalid_config_rejected(bad):
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(bad)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("GROWSHED_MQTT_HOST", "broker")
    monkeypatch.setenv("GROWSHED_MQTT_PORT", "1884")
    monkeypatch.setenv("GROWSHED_MQTT_ENABLED", "0")
    monkeypatch.setenv("GROWSHED_MQTT_USER", "")
    s = Settings.from_env()
    assert (s.mqtt_host, s.mqtt_port, s.mqtt_enabled, s.mqtt_user) == ("broker", 1884, False, None)
