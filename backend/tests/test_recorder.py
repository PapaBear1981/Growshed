import pytest

from growshed import db
from growshed.recorder import Recorder, bucket_for_span, history

KEY = "tent1/sensor/air_temp"
OTHER = "tent1/sensor/air_rh"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "x.db")
    db.migrate(c)
    return c


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_only_configured_numeric_values_are_stored(conn):
    rec = Recorder(conn, {KEY})
    rec.add(KEY, 21.5, 1000)
    rec.add("tent9/sensor/air_temp", 20.0, 1000)  # not in config
    rec.add(KEY, None, 1020)  # failed read
    rec.add(KEY, True, 1040)  # booleans are not measurements
    assert rec.flush() == 1
    assert rec.flush() == 0
    assert count(conn, "reading") == 1


def test_chatty_sources_are_throttled(conn):
    rec = Recorder(conn, {KEY}, min_interval_s=15)
    for t in range(1000, 1060, 5):
        rec.add(KEY, 20.0, t)
    rec.flush()
    assert count(conn, "reading") == 4  # 1000, 1015, 1030, 1045


def test_history_short_range_is_per_minute_and_aligned(conn):
    rec = Recorder(conn, {KEY, OTHER})
    rec.add(KEY, 20.0, 600)
    rec.add(KEY, 22.0, 630)
    rec.add(KEY, 30.0, 720)
    rec.add(OTHER, 55.0, 660)
    rec.flush()
    out = history(conn, [KEY, OTHER], 600, 780)
    assert out["bucket_s"] == 60
    assert out["t"] == [600, 660, 720, 780]
    assert out["series"][KEY] == [21.0, None, 30.0, None]  # averaged per minute, gaps are None
    assert out["series"][OTHER] == [None, 55.0, None, None]


def test_history_of_unknown_series_is_all_gaps(conn):
    out = history(conn, [KEY], 0, 120)
    assert out["series"][KEY] == [None, None, None]


def test_bucket_for_span():
    assert bucket_for_span(6 * 3600) == 60
    assert bucket_for_span(24 * 3600) == 300
    assert bucket_for_span(7 * 86400) == 300
    assert bucket_for_span(30 * 86400) == 3600


def test_rollup_then_history_uses_summaries_plus_fresh_raw(conn):
    rec = Recorder(conn, {KEY})
    day = 86400 * 100
    for i in range(0, 3600, 30):  # one hour of readings, value = minutes since start
        rec.add(KEY, i / 60, day + i)
    rec.flush()
    rec.rollup(day + 3000)  # summarises buckets that finished before (now - 60 s)
    assert count(conn, "reading_5m") == 9  # 0..2700 exclusive of the 2700 bucket
    rec.rollup(day + 3000)  # idempotent
    assert count(conn, "reading_5m") == 9

    out = history(conn, [KEY], day, day + 3599 + 13 * 3600)  # > 12 h span -> 5-minute buckets
    values = [v for v in out["series"][KEY] if v is not None]
    assert out["bucket_s"] == 300
    assert len(values) == 12  # 9 from summaries + 3 straight from raw
    assert values[0] == pytest.approx(2.25) and values[-1] == pytest.approx(57.25)


def test_hourly_rollup_and_long_range(conn):
    rec = Recorder(conn, {KEY})
    day = 86400 * 100
    for i in range(0, 3 * 3600, 60):
        rec.add(KEY, 10.0 if i < 3600 else 20.0, day + i)
    rec.flush()
    rec.rollup(day + 3 * 3600 + 120)
    assert count(conn, "reading_1h") == 3
    out = history(conn, [KEY], day, day + 20 * 86400)
    assert out["bucket_s"] == 3600
    assert out["series"][KEY][:3] == [10.0, 20.0, 20.0]


def test_prune_never_deletes_unsummarised_data(conn):
    rec = Recorder(conn, {KEY})
    old = 86400 * 100
    rec.add(KEY, 1.0, old)
    rec.flush()
    rec.prune(old + 90 * 86400)  # past retention, but not rolled up yet
    assert count(conn, "reading") == 1
    rec.rollup(old + 90 * 86400)
    rec.prune(old + 90 * 86400)
    assert count(conn, "reading") == 0
    assert count(conn, "reading_5m") == 1  # the summary survives for a year
