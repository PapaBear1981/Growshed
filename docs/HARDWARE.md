# Hardware

Prices are rough 2026 ballparks to aid planning. Verify before buying.

## 1. Power budget

Basement circuits are typically 15 A / 120 V and often shared with lights and other outlets.
**Map which outlets share a breaker** (flip breakers, note what goes dead) and keep the
continuous load on each ≤ 80 % (1,440 W on 15 A, 1,920 W on 20 A).

| Load | Watts (est.) |
|---|---|
| Grow lights (per tent) | **TBD — measure** (typ. 100–300 W for 2×2 to 3×3 tents, 300–650 W for 4×4) |
| Inline exhaust fan (per tent) | 20–60 |
| Clip-on circulation fan(s) (per tent) | 5–20 |
| Aquarium heater (control bucket) | 100–300 |
| Air pump(s) | 10–30 |
| RDWC circulation pump | 20–40 |
| Tower pump | 10–25 |
| Room dehumidifier | 300–700 (usually on its own outlet/circuit) |
| Small tent heater (only if needed) | 200–400 |
| Pi, nodes, 12 V supply, tablet | ~30 |

**Two 4×4 tents:** a typical 4×4 LED is 400–480 W, so two tents of lights alone are ~900 W,
plus fans, pumps, the water heater and the tower tent. Expect to **split the tents across two
circuits**, with the dehumidifier on a third if possible.

Each device in `config.yaml` gets a `circuit` field so the backend can show load per circuit
(and later enforce a cap).

## 2. Hub

| Item | Notes | ~$ |
|---|---|---|
| Raspberry Pi 4 8GB | Have | — |
| USB 3 SSD (≥ 128 GB) + adapter | Boot drive | 30 |
| Official PSU + small UPS | Rides through blips; clean shutdown | 40–60 |
| Case with fan | | 15 |
| Ethernet cable (if reachable) | More reliable than WiFi | — |

## 3. Nodes (ESP32 + ESPHome)

Any supported board (see the table in [`firmware/README.md`](../firmware/README.md); the
ESP32-WROOM DevKit is the recommended one) on screw-terminal breakout boards, in the 3D-printed
enclosure from [`hardware/enclosure/`](../hardware/enclosure/README.md), mounted **outside**
each tent with the cable slots facing down (sensors go inside on cables through a tent port).

### Node power

Every node is powered the same way, from one **UL-listed 12 V DC wall adapter**
(2 A for tent nodes, 3–5 A for the water and dosing nodes, which also run 12 V pumps):

```
12 V adapter → barrel jack → 2 A inline fuse ─┬─ buck converter (12 V → 5 V) → ESP32 5V/VIN pin
                                              └─ 12 V rail → MOSFET board → 12 V pumps/fans
                                   (all grounds joined)
```

| Part | Notes | ~$ |
|---|---|---|
| 12 V wall adapter | UL/ETL listed, 5.5×2.1 mm barrel | 10 |
| Panel-mount DC barrel jack | Measure its thread; the enclosure hole is parametric | 2 |
| Inline blade fuse holder + 2 A fuse | On the 12 V input | 3 |
| Buck converter 12 V → 5 V | A **fixed 5 V** module is safest. If using an adjustable LM2596, set it to 5.0–5.1 V with a multimeter **before** connecting the ESP32 | 3 |
| 470–1000 µF capacitor across 5 V | Optional; rides through pump-start dips | 1 |

Rules:
- **Never connect USB and the 5 V buck at the same time.** Unplug 12 V when flashing over USB; after the first flash, update over WiFi (OTA).
- Sensors run from the ESP32's 3.3 V pin. Relay-box signal inputs connect straight to GPIOs (they are opto-isolated and accept 3.3 V).
- A tent node with no 12 V loads can instead run from a good 5 V USB charger: the USB cable drops into one of the cable slots.
- Nodes need no battery backup. On power return they boot, restore their setpoints and resume.

### `tent<N>` node (one per tent)
| Part | Interface | Purpose | ~$ |
|---|---|---|---|
| SHT45 breakout | I²C | Tent air temp/RH, at canopy height, shaded from the light | 15 |
| BH1750 | I²C | Light level (confirms the lights actually turned on) | 5 |
| DS3231 RTC | I²C | Time for fallback schedules with no network | 5 |
| Leak sensor (probe type) | GPIO | Tent floor tray | 10 |
| Capacitive soil sensors ×N (if soil pots here) | ADC | Soil moisture | 3 each |
| SCD41 (Phase 5) | I²C | CO₂ | 50 |
| Outputs → relay boxes | GPIO | Lights, exhaust fan, (tent heater) | — |
| **Tower tent only:** DS18B20 + float switch + relay output | 1-Wire, GPIO | Tower reservoir temp, tower LOW, tower pump | 10 |

### `water` node (near the RDWC control bucket)
| Part | Interface | Purpose | ~$ |
|---|---|---|---|
| DS18B20 waterproof | 1-Wire | Control bucket temp | 3 |
| Vertical float switches ×2–3 | GPIO | Control bucket LOW/HIGH, (top-off tank LOW) | 15 |
| Leak sensors ×2 | GPIO | Under the control bucket and the top-off tank | 20 |
| SHT45 | I²C | **Room** (basement) temp/RH, outside the tents | 15 |
| Atlas EZO-pH + probe (Phase 3) | I²C, isolated carrier | pH | ~170 |
| Atlas EZO-EC + K1.0 probe (Phase 3) | I²C, isolated carrier | EC | ~200 |
| Outputs → relay boxes / MOSFETs | GPIO | Water heater, air pump, RDWC pump, top-off pump | — |

**pH/EC isolation is mandatory:** two probes in the same water without isolation interfere
with each other. Use Atlas's isolated carrier boards.

**Budget alternative:** DFRobot Gravity pH/EC (~$60 total) works for learning, but those
probes drift when left submerged 24/7. Upgrade before auto-dosing.

### `dosing` node (Phase 4)
| Part | Purpose | ~$ |
|---|---|---|
| 12 V peristaltic pumps ×4 | pH down, pH up, nutrient A, nutrient B | 60 |
| 4-ch logic-level MOSFET board (flyback diodes) | Drive pumps | 10 |
| 12 V 3 A supply | Pumps | 15 |
| Leak sensor | Dosing tray | 10 |

## 4. Mains switching

**Digital Loggers "IoT Power Relay" (or equivalent pre-built box)**: a 3–48 V signal from an
ESP32 GPIO switches its outlets. Each box has normally-OFF, normally-ON and always-ON outlets.

Suggested grouping (one box per signal):
- Per tent: **lights**, **exhaust fan** (two boxes per tent, or lights on a box + exhaust on a 12 V/low-voltage relay if it's a DC fan)
- Water heater
- RDWC pump + air pump: **normally-ON** outlets (fail running)
- Tower pump (switched by the tower tent's node)

Small 12 V loads (top-off pump, DC fans) can run from a MOSFET or low-voltage relay.

**Inline fans:** many popular inline fans use proprietary controllers. For Phase 2 we switch
fan power on/off (set the fan's own speed knob to a sensible level). Variable speed is Phase 5.

**Dehumidifier:** let it run on its own humidistat. We only *monitor* room RH. Choose a model
that auto-restarts after a power loss.

## 5. Other
- Grow tents with waterproof floor liners; spill trays sized to each reservoir's full volume.
- Titanium aquarium heater, 100–300 W, sized to the total water volume.
- Plug-in watt meter to measure the lights.
- Fresh-water top-off tank (e.g. 5–7 gal jug) with its own tray.
- Carbon filter per tent (if smell matters).
- Smoke detector for the grow area.
- Old tablet + wall mount + charger.

## 6. Pin assignments

Pins depend on the board. They are defined in the board profiles (`firmware/boards/*.yaml`)
and listed per board in [`firmware/README.md`](../firmware/README.md#wiring-pins-per-board-profile).
