from pathlib import Path

import pytest

from tools import detect_boards as d

REPO_ROOT = Path(__file__).resolve().parents[2]


def dev(vid, pid, product=""):
    return d.UsbSerialDevice("/dev/ttyUSB0", vid, pid, product=product)


def test_exact_arduino_boards():
    nano = d.identify(dev("2341", "0070"))
    assert (nano.description, nano.profile) == ("Arduino Nano ESP32", "arduino-nano-esp32")
    uno = d.identify(dev("2341", "0043"))
    assert uno.profile is None and "ESPHome" in uno.note


def test_unknown_arduino_falls_back_to_product_string():
    guess = d.identify(dev("2341", "ffff", product="Arduino Due"))
    assert guess.description == "Arduino Due" and guess.profile is None


@pytest.mark.parametrize("ids", [("10c4", "ea60"), ("1a86", "7523"), ("303a", "1001")])
def test_ambiguous_devices_ask_for_probe(ids):
    guess = d.identify(dev(*ids))
    assert guess.profile is None and "--probe" in guess.note


def test_pico_and_unknown_are_not_nodes():
    assert d.identify(dev("2e8a", "000a")).profile is None
    assert d.identify(dev("dead", "beef")).note == "Not recognised."


@pytest.mark.parametrize(
    ("chip", "profile"),
    [
        ("ESP32-D0WD-V3", "esp32"),
        ("ESP32-PICO-D4", "esp32"),
        ("ESP32-S3", "esp32-s3"),
        ("ESP32-C3", "esp32-c3"),
        ("ESP8266EX", "esp8266"),
        ("ESP32-S2", None),
        ("ESP32-C6", None),
        ("ESP99", None),
    ],
)
def test_guess_from_chip(chip, profile):
    assert d.guess_from_chip(chip).profile == profile


def test_every_profile_the_tool_recommends_exists():
    names = {g.profile for g in d.EXACT.values()} | {
        d.guess_from_chip(c).profile for c in ("ESP32-D0WD", "ESP32-S3", "ESP32-C3", "ESP8266EX")
    }
    for name in names - {None}:
        assert (REPO_ROOT / "firmware" / "boards" / f"{name}.yaml").is_file(), name


@pytest.mark.parametrize(
    ("output", "chip"),
    [
        ("Detecting chip type... ESP32\nChip is ESP32-D0WD-V3 (revision v3.0)", "ESP32-D0WD-V3"),
        ("Chip type:          ESP32-S3 (QFN56) (revision v0.2)", "ESP32-S3"),
        ("Detecting chip type... ESP8266\n", "ESP8266"),
        ("A fatal error occurred: Failed to connect", None),
    ],
)
def test_parse_esptool_output(output, chip):
    assert d.parse_esptool_output(output) == chip


def make_tty(root, name, usb_path, vid, pid, product, tty_subdir):
    """Build a fake sysfs tree like Linux does for a USB serial port."""
    usb = root / "devices" / usb_path
    node = usb / f"{usb_path}:1.0" / tty_subdir
    node.mkdir(parents=True)
    (usb / "idVendor").write_text(vid + "\n")
    (usb / "idProduct").write_text(pid + "\n")
    (usb / "product").write_text(product + "\n")
    tty = root / "class" / "tty" / name
    tty.mkdir(parents=True)
    (tty / "device").symlink_to(node)


def test_scan_reads_sysfs(tmp_path):
    make_tty(tmp_path, "ttyUSB0", "1-1", "10C4", "EA60", "CP2102 USB to UART", "ttyUSB0")
    make_tty(tmp_path, "ttyACM0", "1-2", "2341", "0043", "Arduino Uno", "")
    (tmp_path / "class" / "tty" / "ttyS0").mkdir()  # built-in serial port: ignored
    found = d.scan(tmp_path / "class" / "tty")
    assert [(x.port, x.vid, x.pid, x.product) for x in found] == [
        ("/dev/ttyACM0", "2341", "0043", "Arduino Uno"),
        ("/dev/ttyUSB0", "10c4", "ea60", "CP2102 USB to UART"),
    ]
    assert d.scan(tmp_path / "missing") == []


def test_main_reports_no_devices(monkeypatch, capsys):
    monkeypatch.setattr(d, "scan", lambda: [])
    assert d.main([]) == 1
    assert "No USB serial devices" in capsys.readouterr().out


def test_main_probe_upgrades_guess(monkeypatch, capsys):
    monkeypatch.setattr(d, "scan", lambda: [dev("10c4", "ea60"), dev("2341", "0043")])
    monkeypatch.setattr(d, "esptool_command", lambda: ["esptool"])
    probed = []
    monkeypatch.setattr(d, "probe_chip", lambda port, cmd: probed.append(port) or "ESP32-S3")
    assert d.main(["--probe"]) == 0
    out = capsys.readouterr().out
    assert "boards/esp32-s3.yaml" in out
    assert len(probed) == 1  # a genuine Arduino is never probed (probing resets the board)
