"""Draw the node wiring diagrams (SVG) from the firmware's own pin assignments.

Run from the repo root after changing a board profile or what a node measures:

    python -m tools.wiring_diagrams                # ESP32 DevKit -> docs/wiring/*.svg
    python -m tools.wiring_diagrams --board esp32-s3 --out /tmp/s3

The pin numbers are read from firmware/boards/<board>.yaml, so the drawings cannot
drift away from what the firmware expects. A test fails if the committed SVGs are stale.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Wire colours. The I2C four follow the Qwiic / STEMMA QT cable convention.
NETS = {
    "3V3": ("#d62828", "3.3 V"),
    "GND": ("#1a1a1a", "Ground"),
    "SDA": ("#2a78d6", "I2C data"),
    "SCL": ("#e0a800", "I2C clock"),
    "1W": ("#8e44ad", "1-Wire data"),
    "IN1": ("#1b9e77", "Input 1"),
    "IN2": ("#d95f02", "Input 2"),
    "IN3": ("#a6761d", "Input 3"),
    "IN4": ("#e7298a", "Input 4"),
    # Analog inputs reuse colours from nets that never appear on the same node.
    "ADC1": ("#d95f02", "Analog 1"),
    "ADC2": ("#a6761d", "Analog 2"),
    "ADC3": ("#e7298a", "Analog 3"),
    "ADC4": ("#8e44ad", "Analog 4"),
    # Outputs are drawn on their own diagrams, so they can reuse colours too.
    "OUT1": ("#2a78d6", "Output 1"),
    "OUT2": ("#e0a800", "Output 2"),
    "OUT3": ("#1b9e77", "Output 3"),
    "OUT4": ("#d95f02", "Output 4"),
    "OUT5": ("#8e44ad", "Output 5"),
    "OUT6": ("#e7298a", "Output 6"),
}
NET_PIN = {"SDA": "pin_sda", "SCL": "pin_scl", "1W": "pin_onewire", "IN1": "pin_in1",
           "IN2": "pin_in2", "IN3": "pin_in3", "IN4": "pin_in4", "ADC1": "pin_adc1",
           "ADC2": "pin_adc2", "ADC3": "pin_adc3", "ADC4": "pin_adc4",
           **{f"OUT{i}": f"pin_out{i}" for i in range(1, 7)}}  # fmt: skip


@dataclass
class Part:
    name: str
    where: str
    pins: list[tuple[str, str]]  # (label on the part, net)
    note: str = ""


@dataclass
class Diagram:
    slug: str
    title: str
    parts: list[Part]
    notes: list[str] = field(default_factory=list)


def sht45(where: str) -> Part:
    return Part("SHT45 temperature / humidity", where,
                [("VIN", "3V3"), ("GND", "GND"), ("SCL", "SCL"), ("SDA", "SDA")])  # fmt: skip


def leak(what: str, net: str) -> Part:
    return Part(f"Leak sensor module: {what}", "sensing plate on the floor of the spill tray",
                [("VCC", "3V3"), ("GND", "GND"), ("DO", net)])  # fmt: skip


def float_switch(what: str, net: str, note: str) -> Part:
    return Part(f"Float switch: {what}", "either wire to either terminal",
                [("wire", net), ("wire", "GND")], note)  # fmt: skip


def soil(n: int) -> Part:
    return Part(f"Capacitive soil moisture sensor: pot {n}", "pushed into the soil up to the line",
                [("VCC", "3V3"), ("GND", "GND"), ("AOUT", f"ADC{n}")])  # fmt: skip


def relay_box(what: str, net: str, outlet: str = "normally OFF") -> Part:
    return Part(f"Relay outlet box: {what}", f"plug the load into a '{outlet}' outlet",
                [("+ signal", net), ("- signal", "GND")])  # fmt: skip


DS18B20 = "DS18B20 waterproof probe: {}"
PULLUP = Part("4.7 kΩ resistor", "between the two terminals, at the node",
              [("end", "3V3"), ("end", "1W")], "Needed once per node, not per probe.")  # fmt: skip
TENT_PARTS = [
    sht45("inside the tent at plant height, shaded from the light"),
    Part(
        "BH1750 light sensor",
        "inside the tent, facing the light",
        [("VCC", "3V3"), ("GND", "GND"), ("SCL", "SCL"), ("SDA", "SDA")],
        "Leave the ADDR pin unconnected.",
    ),  # fmt: skip
    Part(
        "DS3231 clock",
        "inside the enclosure",
        [("VCC", "3V3"), ("GND", "GND"), ("SDA", "SDA"), ("SCL", "SCL")],
    ),  # fmt: skip
    leak("tent floor", "IN1"),
]
COMMON_NOTES = [
    "Wires join only where there is a dot. Lines that simply cross are not connected.",
    "Power the board from a USB charger. Never connect 5 V to any of these pins.",
]

DIAGRAMS = [
    Diagram("tent-node", "Tent node (tent1): sensors", TENT_PARTS, COMMON_NOTES),
    Diagram(
        "tent-soil-node",
        "Tent node with soil pots (tent2): sensors",
        TENT_PARTS
        + [
            float_switch(
                "watering tank low", "IN2", "Float hangs DOWN (switch open) when the tank is low."
            )
        ]
        + [soil(n) for n in (1, 2, 3, 4)],
        COMMON_NOTES + ["Fewer pots: leave out the sensors you do not need, from the bottom up."],
    ),
    Diagram(
        "tower-tent-node",
        "Tower tent node (tent3): sensors",
        TENT_PARTS
        + [
            Part(
                DS18B20.format("tower reservoir"),
                "in the tower's water",
                [("red", "3V3"), ("black", "GND"), ("yellow", "1W")],
            ),  # fmt: skip
            PULLUP,
            float_switch(
                "tower reservoir low",
                "IN2",
                "Float hangs DOWN (switch open) when the water is low.",
            ),
        ],
        COMMON_NOTES,
    ),
    Diagram(
        "water-node",
        "Water node (RDWC reservoir): sensors",
        [
            Part(
                DS18B20.format("control bucket"),
                "in the reservoir water",
                [("red", "3V3"), ("black", "GND"), ("yellow", "1W")],
            ),  # fmt: skip
            PULLUP,
            sht45("in open basement air, away from the tents' exhaust"),
            float_switch(
                "reservoir LOW", "IN1", "Float hangs DOWN (switch open) when the water is low."
            ),
            float_switch(
                "reservoir FULL", "IN2", "Float lifts UP (switch closed) at the full mark."
            ),
            leak("under the reservoir", "IN3"),
            leak("under the top-off tank", "IN4"),
        ],
        COMMON_NOTES,
    ),
]


OUTPUT_NOTES = [
    "Wires join only where there is a dot. Lines that simply cross are not connected.",
    "These are low-voltage signal wires only. Mains stays inside the relay boxes.",
]
TENT_OUTPUTS = [relay_box("grow lights", "OUT1"), relay_box("exhaust fan", "OUT2")]
MOSFET_NOTE = "Pumps and the 12 V supply go on the board's power terminals."

DIAGRAMS += [
    Diagram("tent-outputs", "Tent node (tent1): outputs", TENT_OUTPUTS, OUTPUT_NOTES),
    Diagram(
        "tent-soil-outputs",
        "Tent node with soil pots (tent2): outputs",
        TENT_OUTPUTS
        + [
            Part(
                "4-channel MOSFET board: watering pumps",
                "inside or beside the enclosure",
                [
                    ("IN1 (pot 1)", "OUT3"),
                    ("IN2 (pot 2)", "OUT4"),
                    ("IN3 (pot 3)", "OUT5"),
                    ("IN4 (pot 4)", "OUT6"),
                    ("GND", "GND"),
                ],
                MOSFET_NOTE,
            ),  # fmt: skip
        ],
        OUTPUT_NOTES
        + ["The 12 V supply's minus must connect to the node's GND (the board does this)."],
    ),
    Diagram(
        "tower-tent-outputs",
        "Tower tent node (tent3): outputs",
        TENT_OUTPUTS + [relay_box("tower pump", "OUT3")],
        OUTPUT_NOTES,
    ),
    Diagram(
        "water-outputs",
        "Water node (RDWC reservoir): outputs",
        [
            relay_box("water heater", "OUT1"),
            relay_box("air pump", "OUT2", "normally ON"),
            relay_box("circulation pump", "OUT3", "normally ON"),
            Part(
                "MOSFET module: 12 V top-off pump",
                "inside or beside the enclosure",
                [("SIG", "OUT4"), ("GND", "GND")],
                MOSFET_NOTE,
            ),  # fmt: skip
        ],
        OUTPUT_NOTES
        + ["Normally-ON outlets keep the air and circulation pumps running if the node dies."],
    ),
]


DIAGRAMS += [
    Diagram(
        "water-chemistry",
        "Water node (RDWC reservoir): pH and EC probes",
        [
            Part(
                "Analog pH board (BNC probe)",
                "board in the enclosure, probe in the control bucket",
                [("V+", "3V3"), ("G", "GND"), ("Po", "ADC1")],
                "For 3.3 V boards. A 5 V-only board needs a divider (BUILD.md).",
            ),  # fmt: skip
            Part(
                "Analog TDS / EC board",
                "board in the enclosure, probe in the control bucket",
                [("VCC", "OUT5"), ("GND", "GND"), ("A", "ADC2")],
                "Powered from an output pin so it is only on while being read.",
            ),  # fmt: skip
        ],
        COMMON_NOTES + ["Keep the two probes at least a hand's width apart in the bucket."],
    ),
]


def read_profile(board: str) -> dict[str, str]:
    """The substitutions block of a board profile (kept dependency-free: no YAML library)."""
    text = (REPO_ROOT / "firmware" / "boards" / f"{board}.yaml").read_text(encoding="utf-8")
    return {k: v.strip().strip('"') for k, v in re.findall(r"^  (\w+):\s*(.+)$", text, re.M)}


# Layout constants (pixels)
ROW = 26
BOARD_X, BOARD_W = 30, 190
PART_X, PART_W = 560, 340
LANE_X0, LANE_GAP = 262, 31
FONT = "font-family='Helvetica, Arial, sans-serif'"


def render(diagram: Diagram, profile: dict[str, str]) -> str:
    used = [net for net in NETS if any(net == n for p in diagram.parts for _, n in p.pins)]
    missing = [n for n in used if n in NET_PIN and NET_PIN[n] not in profile]
    if missing:
        raise ValueError(f"{profile.get('board_label')}: no pin for {missing} ({diagram.slug})")
    lane = {net: LANE_X0 + i * LANE_GAP for i, net in enumerate(used)}

    out: list[str] = []
    wires: list[str] = []
    dots: list[str] = []
    ends: dict[str, list[float]] = {net: [] for net in used}

    def text(x, y, s, size=13, weight="normal", fill="#1a1a1a", anchor="start") -> str:
        return (f"<text x='{x}' y='{y}' font-size='{size}' font-weight='{weight}' fill='{fill}' "
                f"text-anchor='{anchor}' {FONT}>{escape(s)}</text>")  # fmt: skip

    def wire(net: str, x1: float, x2: float, y: float) -> None:
        colour = NETS[net][0]
        # A white halo under each horizontal run makes crossings read as bridges.
        wires.append(f"<line x1='{x1}' y1='{y}' x2='{x2}' y2='{y}' stroke='#ffffff' "
                     f"stroke-width='7'/>")  # fmt: skip
        wires.append(f"<line x1='{x1}' y1='{y}' x2='{x2}' y2='{y}' stroke='{colour}' "
                     f"stroke-width='3'/>")  # fmt: skip
        dots.append(f"<circle cx='{lane[net]}' cy='{y}' r='4.5' fill='{colour}'/>")
        ends[net].append(y)

    # Parts, stacked on the right. They start below the board so that a wire leaving the
    # board never runs along the same line as a wire entering a part.
    board_h = 54 + ROW * len(used)
    by = 96
    y = by + board_h + 22
    for part in diagram.parts:
        height = 44 + ROW * len(part.pins) + (20 if part.note else 0)
        out.append(f"<rect x='{PART_X}' y='{y}' width='{PART_W}' height='{height}' rx='8' "
                   f"fill='#f6f8f4' stroke='#8a958c'/>")  # fmt: skip
        out.append(text(PART_X + 12, y + 20, part.name, 14, "bold"))
        out.append(text(PART_X + 12, y + 36, part.where, 11, fill="#5f6f65"))
        for i, (label, net) in enumerate(part.pins):
            py = y + 58 + i * ROW
            out.append(f"<rect x='{PART_X - 7}' y='{py - 7}' width='14' height='14' rx='3' "
                       f"fill='#ffffff' stroke='{NETS[net][0]}' stroke-width='2'/>")  # fmt: skip
            out.append(text(PART_X + 14, py + 4, label, 12, "bold"))
            wire(net, lane[net], PART_X - 7, py)
        if part.note:
            out.append(text(PART_X + 12, y + height - 9, part.note, 11, fill="#5f6f65"))
        y += height + 14
    parts_bottom = y

    # The ESP32 board, on the left.
    out.append(f"<rect x='{BOARD_X}' y='{by}' width='{BOARD_W}' height='{board_h}' rx='8' "
               f"fill='#e8f1ea' stroke='#2f7d4f' stroke-width='2'/>")  # fmt: skip
    out.append(text(BOARD_X + 12, by + 20, profile["board_label"], 13, "bold"))
    out.append(text(BOARD_X + 12, by + 36, "screw-terminal breakout", 11, fill="#5f6f65"))
    for i, net in enumerate(used):
        py = by + 62 + i * ROW
        label = net if net in ("3V3", "GND") else profile[NET_PIN[net]]
        out.append(text(BOARD_X + BOARD_W - 14, py + 4, label, 12, "bold", anchor="end"))
        out.append(f"<rect x='{BOARD_X + BOARD_W - 7}' y='{py - 7}' width='14' height='14' rx='3' "
                   f"fill='#ffffff' stroke='{NETS[net][0]}' stroke-width='2'/>")  # fmt: skip
        wire(net, BOARD_X + BOARD_W + 7, lane[net], py)

    # Vertical runs and their labels.
    lanes = []
    for net in used:
        colour, meaning = NETS[net]
        lanes.append(f"<line x1='{lane[net]}' y1='{min(ends[net])}' x2='{lane[net]}' "
                     f"y2='{max(ends[net])}' stroke='{colour}' stroke-width='3'/>")  # fmt: skip
        out.append(f"<text x='{lane[net] + 4}' y='88' font-size='11' fill='{colour}' "
                   f"font-weight='bold' transform='rotate(-55 {lane[net] + 4} 88)' {FONT}>"
                   f"{escape(meaning)}</text>")  # fmt: skip

    ny = max(parts_bottom, by + board_h + 30) + 8
    for note in diagram.notes:
        out.append(text(BOARD_X, ny, "• " + note, 12, fill="#3c4a41"))
        ny += 19
    height = ny + 6
    head = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 920 {height}' width='920' "
            f"height='{height}' role='img' aria-label='{escape(diagram.title)} wiring'>"
            f"<rect width='920' height='{height}' fill='#ffffff'/>"
            + text(BOARD_X, 30, diagram.title, 19, "bold"))  # fmt: skip
    return "\n".join([head, *lanes, *wires, *dots, *out, "</svg>"]) + "\n"


def generate(board: str = "esp32") -> dict[str, str]:
    """{file name: SVG text} for every node that fits on this board."""
    profile = read_profile(board)
    out = {}
    for diagram in DIAGRAMS:
        try:
            out[f"{diagram.slug}.svg"] = render(diagram, profile)
        except ValueError:
            continue  # e.g. the water node does not fit on an ESP8266
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wiring_diagrams", description=__doc__.split("\n")[0])
    parser.add_argument("--board", default="esp32", help="profile name in firmware/boards/")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "wiring")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, svg in generate(args.board).items():
        (args.out / name).write_text(svg, encoding="utf-8")
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
