import pytest

from growshed.topics import parse_payload, parse_state_topic, parse_status_topic


def test_parse_state_topic():
    e = parse_state_topic("growshed/tent1/sensor/air_temp/state")
    assert (e.node, e.component, e.entity, e.key) == (
        "tent1",
        "sensor",
        "air_temp",
        "tent1/sensor/air_temp",
    )


@pytest.mark.parametrize(
    "topic",
    [
        "growshed/tent1/sensor/air_temp/command",  # commands are not state
        "growshed/tent1/status",
        "growshed/hub/sensor/x/state",  # the hub is not a node
        "other/tent1/sensor/air_temp/state",
        "growshed/tent1/climate/x/state",  # unsupported component
        "growshed/tent1/sensor/air_temp/extra/state",
        "growshed//sensor/air_temp/state",
    ],
)
def test_parse_state_topic_rejects(topic):
    assert parse_state_topic(topic) is None


def test_parse_status_topic():
    assert parse_status_topic("growshed/water/status") == "water"
    assert parse_status_topic("growshed/hub/status") is None
    assert parse_status_topic("growshed/water/sensor/x/state") is None


@pytest.mark.parametrize(
    ("component", "payload", "expected"),
    [
        ("sensor", "21.50", 21.5),
        ("sensor", " 7 ", 7.0),
        ("sensor", "nan", None),  # failed read must not become a number
        ("sensor", "inf", None),
        ("sensor", "garbage", None),
        ("number", "20", 20.0),
        ("binary_sensor", "ON", True),
        ("binary_sensor", "off", False),
        ("switch", "maybe", None),
        ("text_sensor", "fallback", "fallback"),
    ],
)
def test_parse_payload(component, payload, expected):
    assert parse_payload(component, payload) == expected
