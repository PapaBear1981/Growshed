from pathlib import Path

import pytest

from tools import wiring_diagrams as w

DOCS = Path(__file__).resolve().parents[2] / "docs" / "wiring"


def test_committed_diagrams_match_the_firmware_pins():
    """If this fails, run `python -m tools.wiring_diagrams` and commit the result."""
    generated = w.generate("esp32")
    assert len(generated) == 8 and "water-outputs.svg" in generated
    for name, svg in generated.items():
        assert (DOCS / name).read_text(encoding="utf-8") == svg, name


def test_diagram_shows_the_pins_from_the_board_profile():
    profile = w.read_profile("esp32")
    svg = w.generate("esp32")["water-node.svg"]
    for key in ("pin_sda", "pin_scl", "pin_onewire", "pin_in1", "pin_in2", "pin_in3", "pin_in4"):
        assert f">{profile[key]}<" in svg
    tent = w.generate("esp32")["tent-node.svg"]
    assert f">{profile['pin_in2']}<" not in tent  # a plain tent node uses one input only


def test_other_boards_get_their_own_pins():
    svg = w.generate("esp32-s3")["tent-node.svg"]
    assert ">GPIO8<" in svg and ">GPIO21<" not in svg


def test_node_that_does_not_fit_a_board_is_skipped():
    assert "water-node.svg" not in w.generate("esp8266")  # too few inputs
    assert "tent-node.svg" in w.generate("esp8266")
    assert "tent-soil-node.svg" not in w.generate("esp8266")  # no usable analog pins


def test_main_writes_files(tmp_path, capsys):
    assert w.main(["--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.svg"))) == 8


@pytest.mark.parametrize("diagram", w.DIAGRAMS, ids=lambda d: d.slug)
def test_every_wire_uses_a_known_net(diagram):
    for part in diagram.parts:
        for _, net in part.pins:
            assert net in w.NETS
