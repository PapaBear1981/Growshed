# Hardware

Prices are rough 2026 ballparks to aid planning. Verify before buying.

## 1. Power budget

Two 15 A / 120 V house circuits via 12 AWG outdoor cords. Plan continuous load at ≤ 80% (1,440 W).

**Circuit A — Heat**
| Load | Watts |
|---|---|
| Oil radiator | 1,500 max (most have 600/900/1500 settings) |

**Circuit B — Everything else**
| Load | Watts (est.) |
|---|---|
| Grow lights | **TBD — measure** (keep ≤ ~800 W) |
| Aquarium heater (control bucket) | 100–300 |
| Air pump(s) | 10–30 |
| RDWC circulation pump | 20–40 |
| Tower pump | 10–25 |
| Fans | 20–60 |
| Dehumidifier (if needed) | 200–300 (a small Peltier unit is much less) |
| Pi, nodes, 12 V supply, tablet | ~30 |

If the lights plus everything else exceed ~1,440 W, stagger loads (e.g. the backend never
runs the dehumidifier and the water heater together) or reconsider. The backend gets a
`circuit` field on each device so it can enforce a per-circuit load cap later.

## 2. Hub

| Item | Notes | ~$ |
|---|---|---|
| Raspberry Pi 4 8GB | Have | — |
| USB 3 SSD (≥ 128 GB) + adapter | Boot drive; replaces the SD card | 30 |
| Official PSU + small UPS (or UPS HAT) | Rides through blips; clean shutdown | 40–60 |
| Case with fan | Shed humidity — keep it ventilated, not sealed | 15 |

## 3. Nodes (ESP32 + ESPHome)

Use **ESP32-WROOM DevKit** boards (or ESP32-S3) on screw-terminal breakout boards. Power each
from 5 V USB, or from a 12 V → 5 V buck if it's near the dosing PSU.

### `climate` node
| Part | Interface | Purpose | ~$ |
|---|---|---|---|
| SHT45 breakout | I²C | Air temp/RH (accurate, low drift) | 15 |
| BH1750 | I²C | Light level (confirms lights are actually on) | 5 |
| DS3231 RTC | I²C | Keeps time for fallback schedules with no network | 5 |
| DS18B20 waterproof | 1-Wire | Outdoor temperature | 3 |
| Reed switch | GPIO | Door open | 5 |
| SCD41 (Phase 5) | I²C | CO₂ | 50 |
| Outputs → relay boxes | GPIO | Air heater, lights, exhaust fan, circ fan, humidity device | — |

Mount the SHT45 at plant-canopy height, shaded from the lights, in a ventilated radiation shield.

### `water` node
| Part | Interface | Purpose | ~$ |
|---|---|---|---|
| DS18B20 waterproof ×2 | 1-Wire | Control bucket + tower reservoir temp | 6 |
| Vertical float switches ×3 | GPIO | Control bucket LOW/HIGH, tower LOW | 15 |
| Water leak sensor (probe type) | GPIO | Floor leak | 10 |
| Atlas EZO-pH + probe (Phase 3) | I²C, isolated carrier | pH | ~170 |
| Atlas EZO-EC + K1.0 probe (Phase 3) | I²C, isolated carrier | EC | ~200 |
| Capacitive soil sensors ×N | ADC (or ADS1115) | Soil pots | 3 each |
| Outputs → relay boxes | GPIO | Water heater, air pump, RDWC pump, tower pump, top-off pump/valve | — |

**pH/EC isolation is mandatory:** two probes in the same water without isolation interfere
with each other. Use Atlas's electrically isolated carrier boards for at least one of them
(ideally both).

**Budget alternative:** DFRobot Gravity pH/EC (~$60 total) works for spot checks, but the
lab-grade probes drift when left submerged 24/7. Fine for learning; plan to upgrade before
auto-dosing.

### `dosing` node (Phase 4)
| Part | Purpose | ~$ |
|---|---|---|
| 12 V peristaltic pumps ×4 | pH down, pH up, nutrient A, nutrient B | 60 |
| 4-channel logic-level MOSFET board (with flyback diodes) | Drive the pumps | 10 |
| 12 V 3 A supply | Pumps | 15 |

## 4. Mains switching

**Digital Loggers "IoT Power Relay" (or equivalent pre-built box)**: a 3–48 V signal from an
ESP32 GPIO switches its outlets. Each box has normally-OFF, normally-ON and always-ON outlets.
Confirm the rating covers the radiator (≥ 12.5 A resistive).

Suggested grouping (one box per signal):
1. Air heater (radiator), on Circuit A
2. Lights
3. Water heater
4. RDWC pump + air pump: **normally-ON** outlets (fail running)
5. Tower pump
6. Fans / humidity device

Small 12 V loads (fans, top-off pump) can run from a MOSFET or low-voltage relay instead.

## 5. Other
- Titanium aquarium heater, 200–300 W, in the control bucket (sized to total water volume).
- Plug-in watt meter (Kill-A-Watt style) to measure the lights and the radiator.
- Waterproof junction/project boxes, cable glands, drip loops.
- Old tablet + wall mount + always-on charger (consider a smart-plug charge cycle to spare the battery).
- Foam board insulation, weatherstripping (see PLAN.md §3).

## 6. Pin assignments

To be defined per node in `firmware/<node>.yaml` and mirrored in a table here once wiring is decided.
