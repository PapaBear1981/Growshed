import anyio


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "mqtt_connected": False}


def test_config_endpoint(client):
    body = client.get("/api/config").json()
    assert {"zones", "nodes", "sensors", "devices"} <= body.keys()
    assert any(s["key"] == "air_temp" and s["unit"] == "°C" for s in body["sensors"])


def test_settings_default_update_and_validation(client):
    assert client.get("/api/settings").json() == {"display_units": "imperial"}
    assert client.put("/api/settings", json={"display_units": "metric"}).status_code == 200
    assert client.get("/api/settings").json() == {"display_units": "metric"}
    assert client.put("/api/settings", json={"display_units": "kelvin"}).status_code == 422


def test_websocket_snapshot_then_live_updates(client):
    ingest = client.app.state.ingest
    anyio.run(ingest.handle, "growshed/tent1/sensor/air_temp/state", "22.5", 10.0)
    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["values"]["tent1/sensor/air_temp"]["value"] == 22.5
        assert snap["settings"] == {"display_units": "imperial"}
        assert snap["mqtt_connected"] is False
        assert snap["server_time"] > 0

        client.portal.call(ingest.handle, "growshed/tent1/binary_sensor/leak/state", "ON", 11.0)
        assert ws.receive_json() == {
            "type": "value",
            "key": "tent1/binary_sensor/leak",
            "value": True,
            "ts": 11.0,
        }

        client.put("/api/settings", json={"display_units": "metric"})
        assert ws.receive_json() == {"type": "settings", "display_units": "metric"}

    assert client.get("/api/state").json()["values"]["tent1/binary_sensor/leak"]["value"] is True
