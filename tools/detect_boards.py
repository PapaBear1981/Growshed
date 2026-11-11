"""Detect microcontroller boards plugged into USB and say which firmware profile fits.

Run on the Pi (or any Linux machine) from the repo root:

    python -m tools.detect_boards            # identify by USB id (does not touch the board)
    python -m tools.detect_boards --probe    # also ask Espressif chips what they are
                                             # (needs `pip install esptool`; resets the board)

Why two steps: most ESP32/ESP8266 dev boards show up only as a generic USB-serial
adapter (CP210x, CH340), so the USB id alone cannot tell them apart. --probe uses
esptool to read the actual chip type.

Linux only: it reads /sys/class/tty. No third-party packages needed without --probe.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NOT_A_NODE = "Cannot run the node firmware (ESPHome needs an ESP32 or ESP8266) and has no WiFi."


@dataclass(frozen=True)
class UsbSerialDevice:
    port: str  # e.g. /dev/ttyUSB0
    vid: str  # lowercase hex, e.g. "10c4"
    pid: str
    manufacturer: str = ""
    product: str = ""


@dataclass(frozen=True)
class Guess:
    description: str
    profile: str | None  # file name in firmware/boards/ without .yaml, or None
    note: str = ""


# Boards identified exactly by their USB id.
EXACT: dict[tuple[str, str], Guess] = {
    ("2341", "0070"): Guess("Arduino Nano ESP32", "arduino-nano-esp32"),
    ("2341", "0043"): Guess("Arduino Uno R3", None, NOT_A_NODE),
    ("2341", "0001"): Guess("Arduino Uno", None, NOT_A_NODE),
    ("2341", "0042"): Guess("Arduino Mega 2560", None, NOT_A_NODE),
    ("2341", "0010"): Guess("Arduino Mega 2560", None, NOT_A_NODE),
    ("2341", "8036"): Guess("Arduino Leonardo", None, NOT_A_NODE),
    ("2341", "8037"): Guess("Arduino Micro", None, NOT_A_NODE),
    ("2341", "0058"): Guess("Arduino Nano Every", None, NOT_A_NODE),
    ("2341", "0069"): Guess("Arduino Uno R4 Minima", None, NOT_A_NODE),
    ("2341", "1002"): Guess(
        "Arduino Uno R4 WiFi", None, "Has WiFi, but ESPHome does not support this board."
    ),
    ("2341", "8054"): Guess(
        "Arduino MKR WiFi 1010", None, "Has WiFi, but ESPHome does not support this board."
    ),
    ("2341", "8057"): Guess(
        "Arduino Nano 33 IoT", None, "Has WiFi, but ESPHome does not support this board."
    ),
}

# USB-serial adapter chips: the board behind them could be several things.
SERIAL_BRIDGES = {
    ("10c4", "ea60"): "CP210x",
    ("1a86", "7523"): "CH340",
    ("1a86", "55d4"): "CH9102",
    ("0403", "6001"): "FTDI FT232",
    ("0403", "6015"): "FTDI FT231X",
}

ARDUINO_VENDORS = {"2341", "2a03"}
ESPRESSIF_VENDOR = "303a"
PICO_VENDOR = "2e8a"
TEENSY_VENDOR = "16c0"  # shared vendor id; PJRC's Teensy products are 04xx


def identify(dev: UsbSerialDevice) -> Guess:
    """Best guess from USB ids alone. Never touches the board."""
    key = (dev.vid, dev.pid)
    if key in EXACT:
        return EXACT[key]
    if dev.vid in ARDUINO_VENDORS:
        return Guess(dev.product or "Arduino board", None, NOT_A_NODE)
    if dev.vid == ESPRESSIF_VENDOR:
        return Guess(
            "Espressif board with built-in USB (ESP32-S3, -C3, -S2 or -C6)",
            None,
            "Run again with --probe to find out which.",
        )
    if dev.vid == PICO_VENDOR:
        return Guess(
            dev.product or "Raspberry Pi Pico",
            None,
            "Not usable as a node: the plain Pico has no WiFi, and ESPHome has no MQTT "
            "support on the Pico W.",
        )
    if dev.vid == TEENSY_VENDOR and dev.pid.startswith("04"):
        return Guess(dev.product or "Teensy", None, NOT_A_NODE)
    if key in SERIAL_BRIDGES:
        return Guess(
            f"{SERIAL_BRIDGES[key]} USB-serial adapter: most likely an ESP32 or ESP8266 dev "
            "board (or an Arduino Nano clone)",
            None,
            "Run again with --probe to find out which.",
        )
    return Guess(dev.product or "Unknown USB serial device", None, "Not recognised.")


def guess_from_chip(chip: str) -> Guess:
    """Map an esptool chip name (e.g. "ESP32-D0WD-V3") to a firmware profile."""
    name = chip.upper()
    if name.startswith("ESP32-S3"):
        return Guess(chip, "esp32-s3")
    if name.startswith("ESP32-C3"):
        return Guess(chip, "esp32-c3")
    if name.startswith("ESP8266") or name.startswith("ESP8285"):
        return Guess(chip, "esp8266", "Fine for tent nodes; too few pins for the water node.")
    for family in ("ESP32-S2", "ESP32-C2", "ESP32-C5", "ESP32-C6", "ESP32-H2", "ESP32-P4"):
        if name.startswith(family):
            return Guess(chip, None, "ESPHome supports it, but there is no board profile yet.")
    if name.startswith("ESP32"):
        return Guess(chip, "esp32")
    return Guess(chip, None, "Not recognised.")


# The specific line ("Chip is ESP32-D0WD-V3") beats the generic "Detecting chip type... ESP32".
CHIP_PATTERNS = (
    re.compile(r"(?:Chip is|Chip type:)\s+(ESP[\w-]+)"),
    re.compile(r"Detecting chip type\.\.\.\s+(ESP[\w-]+)"),
)


def parse_esptool_output(text: str) -> str | None:
    for pattern in CHIP_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def esptool_command() -> list[str] | None:
    for exe in ("esptool", "esptool.py"):
        if shutil.which(exe):
            return [exe]
    try:
        import esptool  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "esptool"]


def probe_chip(port: str, command: list[str]) -> str | None:
    """Ask the chip what it is. Returns None if nothing Espressif answers."""
    try:
        result = subprocess.run(
            [*command, "--port", port, "chip_id"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_esptool_output(result.stdout + result.stderr)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def scan(sys_tty: Path = Path("/sys/class/tty")) -> list[UsbSerialDevice]:
    """List USB serial ports (ttyUSB*, ttyACM*) with their USB identity."""
    devices = []
    if not sys_tty.is_dir():
        return devices
    for entry in sorted(sys_tty.iterdir()):
        if not entry.name.startswith(("ttyUSB", "ttyACM")):
            continue
        # The USB device (which owns idVendor) is some levels above the tty's device node.
        node = (entry / "device").resolve()
        for parent in [node, *node.parents][:6]:
            if (parent / "idVendor").is_file():
                devices.append(
                    UsbSerialDevice(
                        port=f"/dev/{entry.name}",
                        vid=_read(parent / "idVendor").lower(),
                        pid=_read(parent / "idProduct").lower(),
                        manufacturer=_read(parent / "manufacturer"),
                        product=_read(parent / "product"),
                    )
                )
                break
    return devices


def describe(dev: UsbSerialDevice, guess: Guess) -> str:
    lines = [f"{dev.port}  [{dev.vid}:{dev.pid}]  {guess.description}"]
    if guess.profile:
        lines.append(f"    use:  board: !include boards/{guess.profile}.yaml")
    else:
        lines.append("    no firmware profile")
    if guess.note:
        lines.append(f"    note: {guess.note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="detect_boards", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--probe", action="store_true", help="identify ESP chips with esptool (resets the board)"
    )
    args = parser.parse_args(argv)

    devices = scan()
    if not devices:
        print("No USB serial devices found. Check the cable (some USB cables are charge-only).")
        return 1

    command = esptool_command() if args.probe else None
    if args.probe and command is None:
        print("--probe needs esptool:  pip install esptool\n")

    for dev in devices:
        guess = identify(dev)
        if (
            command
            and guess.profile is None
            and dev.vid not in ARDUINO_VENDORS | {PICO_VENDOR, TEENSY_VENDOR}
        ):
            chip = probe_chip(dev.port, command)
            if chip:
                guess = guess_from_chip(chip)
            else:
                guess = Guess(
                    guess.description, None, "No ESP chip answered: probably not an ESP board."
                )
        print(describe(dev, guess))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
