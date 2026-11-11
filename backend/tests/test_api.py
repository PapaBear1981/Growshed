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


def test_history_endpoint(client):
    rec = client.app.state.recorder
    rec.add("tent1/sensor/air_temp", 21.0, 1000)
    rec.add("tent1/sensor/air_temp", 23.0, 1030)
    rec.flush()
    body = client.get(
        "/api/history", params={"keys": "tent1/sensor/air_temp", "start": 960, "end": 1080}
    ).json()
    assert body["bucket_s"] == 60 and body["t"] == [960, 1020, 1080]
    assert body["series"]["tent1/sensor/air_temp"] == [21.0, 23.0, None]


def test_history_rejects_bad_requests(client):
    ok = "tent1/sensor/air_temp"
    assert client.get("/api/history", params={"keys": "nope/sensor/x"}).status_code == 422
    assert client.get("/api/history", params={"keys": ""}).status_code == 422
    # on/off sensors are not recorded
    leak = "tent1/binary_sensor/leak"
    assert client.get("/api/history", params={"keys": leak}).status_code == 422
    assert client.get("/api/history", params={"keys": ok, "start": 10, "end": 5}).status_code == 422
    assert client.get("/api/history", params={"keys": ok}).status_code == 200


def test_ingested_readings_reach_history(client):
    ingest = client.app.state.ingest
    anyio.run(ingest.handle, "growshed/tent1/sensor/air_temp/state", "22.5", 5000.0)
    anyio.run(ingest.handle, "growshed/tent9/sensor/air_temp/state", "22.5", 5000.0)
    assert client.app.state.recorder.flush() == 1  # the unconfigured tent9 is not stored


def test_alert_lifecycle_over_api_and_websocket(client):
    app = client.app
    live, engine = app.state.live, app.state.alerts
    assert client.get("/api/alerts").json() == {
        "active": [],
        "recent": [],
        "notifications_configured": False,
    }
    now = engine.started_at
    live.set_node_status("tent1", "online", now)
    live.set_value("tent1/binary_sensor/leak", True, now)
    engine.tick(now)

    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert [a["name"] for a in snap["alerts"]] == ["Leak detected"]
        alert_id = snap["alerts"][0]["id"]
        assert client.post(f"/api/alerts/{alert_id}/ack").json() == {"ok": True}
        pushed = ws.receive_json()
        assert pushed["type"] == "alerts" and pushed["active"][0]["acked_at"] is not None

    assert client.post("/api/alerts/424242/ack").status_code == 404
    body = client.get("/api/alerts").json()
    assert len(body["active"]) == 1 and len(body["recent"]) == 1


def test_test_notification_when_not_configured(client):
    assert client.post("/api/alerts/test").json() == {"configured": False, "sent": False}
