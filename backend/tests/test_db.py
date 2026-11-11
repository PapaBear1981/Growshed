from growshed import db


def test_migrate_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "sub" / "x.db")
    assert db.migrate(conn) == ["001_settings.sql", "002_history_alerts.sql"]
    assert db.migrate(conn) == []


def test_new_migrations_apply_in_order(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_a.sql").write_text("CREATE TABLE a (x);")
    conn = db.connect(":memory:")
    assert db.migrate(conn, mig) == ["001_a.sql"]
    (mig / "002_b.sql").write_text("CREATE TABLE b (y); INSERT INTO a VALUES (1);")
    assert db.migrate(conn, mig) == ["002_b.sql"]
    assert conn.execute("SELECT x FROM a").fetchone()["x"] == 1


def test_settings_roundtrip(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)
    assert db.get_setting(conn, "display_units", "imperial") == "imperial"
    db.set_setting(conn, "display_units", "metric")
    db.set_setting(conn, "display_units", "metric")
    assert db.get_setting(conn, "display_units", "imperial") == "metric"
