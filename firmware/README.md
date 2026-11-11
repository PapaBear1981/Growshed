# Node firmware (ESPHome)

One small file per node (`tent1.yaml`, `tent2.yaml`, `tent3.yaml`, `water.yaml`) that combines:

- a **board profile** from `boards/` (which chip, which pins), and
- **role packages** from `common/` (what the node measures).

The same node file works on any supported board: you change one line.

**Status: Phase 1, monitoring only.** All configs pass `esphome config`, but nothing has been
compiled or run on real hardware yet. Relays, thermostats and interlocks arrive in Phase 2.

## Supported boards

| Board | Profile | Tent nodes | Water node | Notes |
|---|---|---|---|---|
| ESP32 DevKit (WROOM-32, 30- or 38-pin) | `esp32` | yes | yes | **Recommended.** Enough pins for Phase 2 relays |
| ESP32-S3 DevKitC | `esp32-s3` | yes | yes | |
| ESP32-C3 DevKitM / "Super Mini" | `esp32-c3` | yes | yes | Few pins: may run short in Phase 2 |
| Arduino Nano ESP32 | `arduino-nano-esp32` | yes | yes | It is an ESP32-S3 inside |
| ESP8266 (D1 mini, NodeMCU) | `esp8266` | yes | **no** | Too few safe pins for the water node, and too few for Phase 2 relays. Fine as a sensor-only node |
| Arduino Uno / Nano / Mega / Leonardo, Uno R4, MKR, Nano 33 | none | no | no | ESPHome cannot run on these, and the classic ones have no WiFi |
| Raspberry Pi Pico / Pico W | none | no | no | The plain Pico has no WiFi; ESPHome has no MQTT support on the Pico W |
| Teensy (any) | none | no | no | No WiFi, and ESPHome cannot run on it |

## Which board do I have?

Plug the board into the Pi (or any Linux computer) by USB and run, from the repo root:

```bash
python -m tools.detect_boards
```

Most ESP boards only identify as a generic USB adapter. To read the actual chip (this resets
the board, and needs `pip install esptool`):

```bash
python -m tools.detect_boards --probe
```

It prints the line to put in the node file, e.g. `board: !include boards/esp32-s3.yaml`.

## Flashing a node

1. Copy `secrets.example.yaml` to `secrets.yaml` and fill in WiFi and the MQTT node password
   (the `MQTT_NODE_PASSWORD` from the Pi's `.env`).
2. In the node file (e.g. `tent1.yaml`) set the `board:` line to your board's profile.
3. Start the ESPHome dashboard on the Pi and open port 6052:

   ```bash
   docker compose --profile esphome up -d
   ```

4. Plug the board into the Pi by USB, pick the node, and choose *Install → Plug into the
   computer running ESPHome Dashboard*. Later updates go over WiFi.

Within a minute the node appears on the Growshed dashboard. The System page shows its board
type and firmware version.

## Wiring (pins per board profile)

| Signal | `esp32` | `esp32-s3` | `esp32-c3` | `arduino-nano-esp32` | `esp8266` |
|---|---|---|---|---|---|
| I²C SDA | GPIO21 | GPIO8 | GPIO6 | GPIO11 (A4) | GPIO4 (D2) |
| I²C SCL | GPIO22 | GPIO9 | GPIO7 | GPIO12 (A5) | GPIO5 (D1) |
| 1-Wire (DS18B20, needs a 4.7 kΩ pull-up to 3.3 V) | GPIO4 | GPIO4 | GPIO4 | GPIO5 | GPIO2 (D4) |
| Input 1 | GPIO32 | GPIO5 | GPIO0 | GPIO6 | GPIO14 (D5) |
| Input 2 | GPIO33 | GPIO6 | GPIO1 | GPIO7 | GPIO12 (D6) |
| Input 3 | GPIO25 | GPIO7 | GPIO3 | GPIO8 | GPIO13 (D7) |
| Input 4 | GPIO26 | GPIO15 | GPIO10 | GPIO9 | — |

The Arduino Nano ESP32 and ESP32-C3 pin choices are the least certain: check them against
your board's pinout diagram before wiring, and edit the profile if needed.

What the inputs are used for:

| Node | Input 1 | Input 2 | Input 3 | Input 4 |
|---|---|---|---|---|
| tent1, tent2 | Floor leak probe | — | — | — |
| tent3 (tower tent) | Floor leak probe | Tower low float | — | — |
| water | Reservoir low float | Reservoir high float | Leak under reservoir | Leak under top-off tank |

All inputs use the chip's internal pull-up: wire each switch or probe between the pin and GND.
Low floats are wired so that a broken wire reads as "low" (the safe direction). A leak probe
with a broken wire reads "dry", so test the leak probes with a wet finger now and then.

I²C devices: SHT45 (air temperature/humidity), BH1750 (light), DS3231 (clock) on tent nodes;
SHT45 (room climate) on the water node. All share the same two I²C wires.

## Adding a board profile

Copy the closest file in `boards/`, change the `board:` id and the pins, then check it:

```bash
docker run --rm -v "$PWD/firmware":/config ghcr.io/esphome/esphome:stable config tent1.yaml
```
