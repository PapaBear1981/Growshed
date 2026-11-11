from growshed.journal import image_extension

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


def test_image_extension_goes_by_content():
    assert image_extension(JPEG) == "jpg" and image_extension(PNG) == "png"
    assert image_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert image_extension(b"<html><script>") is None and image_extension(b"") is None


def test_dose_log(client):
    assert client.get("/api/doses").json() == []
    body = {"zone": "rdwc", "product": "pH down", "amount": 4, "unit": "mL", "note": " first "}
    dose_id = client.post("/api/doses", json=body).json()["id"]
    client.post("/api/doses", json={**body, "product": "Nutrient A", "amount": 20, "ts": 1000})
    rows = client.get("/api/doses", params={"zone": "rdwc"}).json()
    assert [r["product"] for r in rows] == ["pH down", "Nutrient A"]  # newest first
    assert rows[0]["note"] == "first" and rows[1]["ts"] == 1000
    assert len(client.get("/api/doses", params={"since": 2000}).json()) == 1
    assert client.get("/api/doses", params={"zone": "tower"}).json() == []
    assert client.delete(f"/api/doses/{dose_id}").json() == {"ok": True}
    assert client.delete(f"/api/doses/{dose_id}").status_code == 404


def test_dose_log_rejects_bad_input(client):
    ok = {"zone": "rdwc", "product": "pH down", "amount": 4}
    for change in ({"zone": "nowhere"}, {"amount": 0}, {"amount": -3}, {"product": ""},
                   {"unit": "gallons"}):  # fmt: skip
        assert client.post("/api/doses", json={**ok, **change}).status_code == 422


def test_plants_and_journal(client):
    plant = {"zone": "tent1", "name": "Butterhead lettuce", "variety": "Rex", "started_at": 5000}
    plant_id = client.post("/api/plants", json=plant).json()["id"]
    assert client.post("/api/plants", json={**plant, "zone": "moon"}).status_code == 422
    client.post("/api/plants", json={"zone": "tower", "name": "Strawberries"})

    entry_id = client.post("/api/journal", json={"plant_id": plant_id, "text": "Sprouted"}).json()[
        "id"
    ]
    client.post("/api/journal", json={"text": "Cleaned the reservoir"})
    assert client.post("/api/journal", json={"plant_id": 999, "text": "x"}).status_code == 422
    assert len(client.get("/api/journal").json()) == 2
    mine = client.get("/api/journal", params={"plant_id": plant_id}).json()
    assert [e["text"] for e in mine] == ["Sprouted"]

    # harvest: ended plants sort after growing ones
    done = client.put(f"/api/plants/{plant_id}", json={**plant, "ended_at": 9000, "notes": "tasty"})
    assert done.json() == {"ok": True}
    plants = client.get("/api/plants").json()
    assert [p["name"] for p in plants] == ["Strawberries", "Butterhead lettuce"]
    assert plants[1]["ended_at"] == 9000 and plants[1]["started_at"] == 5000
    assert client.put("/api/plants/999", json=plant).status_code == 404
    assert client.delete(f"/api/journal/{entry_id}").json() == {"ok": True}


def test_photo_upload_is_validated_and_served(client, settings):
    entry_id = client.post("/api/journal", json={"text": "Day 10"}).json()["id"]
    url = f"/api/journal/{entry_id}/photo"
    assert client.put(url, content=b"<script>alert(1)</script>").status_code == 415
    assert client.put(url, content=b"\xff\xd8\xff" + b"0" * (7 * 1024 * 1024)).status_code == 413
    assert client.put("/api/journal/999/photo", content=JPEG).status_code == 404

    first = client.put(url, content=JPEG).json()["photo"]
    assert first.startswith(f"{entry_id}-") and first.endswith(".jpg")
    assert client.get(f"/api/photos/{first}").content == JPEG
    second = client.put(url, content=PNG).json()["photo"]  # replacing removes the old file
    photos = settings.db_path.parent / "photos"
    assert [p.name for p in photos.iterdir()] == [second]

    # only files we stored are served: no reaching outside the photo folder
    (settings.db_path.parent / "secret.txt").write_text("nope")
    assert client.get("/api/photos/..%2Fsecret.txt").status_code == 404
    assert client.get("/api/photos/secret.txt").status_code == 404

    client.delete(f"/api/journal/{entry_id}")
    assert list(photos.iterdir()) == []
    assert client.get(f"/api/photos/{second}").status_code == 404
