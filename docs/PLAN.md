# Growshed — Project Plan

A controller for an indoor hydroponics garden in a **finished basement**, using **grow tents**.
It monitors and controls the water, air temperature, humidity, lights, fans, air pumps and
(later) nutrient dosing. The GUI works on phones, a laptop and a wall-mounted old tablet.

> History: originally planned for an uninsulated backyard shed, then moved to the basement.
> Freeze protection, extension cords and insulation planning were dropped. Water-damage and
> household-humidity protection took their place.

Read with: [ARCHITECTURE.md](ARCHITECTURE.md), [SAFETY.md](SAFETY.md),
[HARDWARE.md](HARDWARE.md), [MQTT.md](MQTT.md).

---

## 1. What we're growing and how

| System | Description | Automation level |
|---|---|---|
| **RDWC** | One central "control" bucket (reservoir) feeding several DWC buckets, with a return pump | Fully monitored. Water heat, air and top-off are controlled. pH/EC is monitored now and auto-dosed later |
| **Kratky** | Passive jars/totes, no pumps | Monitoring only (optional level/temp) |
| **Strawberry tower** | Vertical tower with its own small reservoir and a pump on a cycle timer | Pump cycles, level monitoring. **Needs a tall tent** (tower height + ~18" for light) |
| **Soil pots** | Ordinary potted plants in dirt, each with a moisture sensor and (Phase 2) its own small watering pump fed from a plain-water tank | Moisture monitoring and "soil dry" alerts now. Automatic watering in Phase 2, under the limits in SAFETY.md §4b |

Each grow tent is a **zone** with its own climate, lights and exhaust, and its own node.
The system is config-driven for **N tents**. Starting layout:

| Tent | Size | Contents | Node |
|---|---|---|---|
| Tent 1 | 4×4 ft | TBD (RDWC / Kratky / soil) | `tent1` |
| Tent 2 | 4×4 ft | TBD (RDWC / Kratky / soil) | `tent2` |
| Tower tent | **TBD** (see below) | Strawberry tower + its reservoir and pump | `tent3` |

**Sizing the tower tent:** decide after choosing the tower.
- Footprint: tower's widest point + 8–12" clear on every side (room to reach the back plants and for airflow). One tower up to ~16" wide fits a 2×2; a **3×3 is much easier to work in** and leaves the corners free for lights.
- Height: tower height including its reservoir base + 12" if lit from the sides, or + 24" if lit from above. Most 5 ft towers need a 72–80" tall tent.
- Lighting: a single overhead light starves the lower tiers. Plan on 2–4 **vertical LED bars** in the tent corners.

## 2. Decisions made

| Topic | Decision | Reason |
|---|---|---|
| Location | Finished basement, grow tents | Unused space, stable temperatures, inside the house |
| Brain | Raspberry Pi 4 (8GB), booting from a **USB SSD** | SD cards die under constant database writes |
| Field nodes | **ESP32-family boards running ESPHome** (ESP32, -S3, -C3, Arduino Nano ESP32; ESP8266 for sensor-only tent nodes), chosen per node with a one-line board profile: one node per tent + one water node (+ dosing node later). Classic Arduinos and the Pico W cannot be nodes (see `firmware/README.md`) | Declarative YAML, proven drivers, OTA, native MQTT. A node per tent avoids I²C address clashes and isolates failures |
| Messaging | MQTT (Mosquitto on the Pi) | Standard and debuggable. Matches ESPHome conventions |
| Backend | Python 3.11+, FastAPI, asyncio, `aiomqtt`, SQLite | Readable and needs no extra servers |
| Frontend | Svelte 4 + Vite (static build) + **uPlot** charts | Small bundles. Must run on an **old tablet** |
| Mains switching | **Pre-built relay outlet boxes** (Digital Loggers IoT Power Relay or equivalent), driven by ESP32 GPIO | No DIY mains wiring. Nodes can switch loads with the Pi down |
| Tent climate | Lights are the main heat source. An inline exhaust fan per tent (with optional carbon filter) controls temp/RH. A small tent heater only if measurements show it's needed | A basement is typically 60–68 °F; lights add 5–15 °F inside a tent |
| Room humidity | A basement dehumidifier keeps the **room** ≤ 55–60 % RH | Tents exhaust moisture into the house. A finished basement has drywall and carpet/flooring to protect |
| Water heat | Titanium aquarium heater in the control bucket | Basement water may sit ~60 °F. DWC roots want 65–68 °F |
| Power | Existing basement circuits, **GFCI-protected**, mapped and budgeted (HARDWARE.md §1) | No extension-cord runs to an outbuilding anymore |
| Water containment | Every reservoir/bucket sits in a **spill tray sized for its full volume**. Leak sensors in every tent | A leak now damages the house, not a shed floor |
| Top-off source | A **fresh-water tank/jug**, never a direct connection to house plumbing | A stuck valve on a house line is a flood |
| Dosing | Manual for now. Auto-dosing in Phase 4 | Bad auto-dosing kills plants overnight |
| GUI devices | Phone, laptop, old tablet in kiosk mode | One responsive web app |
| Remote access | Tailscale (no router port-forwarding) | Secure and zero-config |
| Alerts | ntfy push notifications | Free and works on Android and iOS |
| Units | Stored internally in **SI**. Displayed in **°F** by default (user setting) | One canonical unit avoids conversion bugs |

## 3. Basement-specific considerations

1. **Water damage is the #1 risk.** Spill trays, leak sensors, automatic pump/top-off shutoff, no plumbing connections. A floor drain nearby is a bonus.
2. **Household humidity and mold.** Tents push humid air into the basement. Monitor **room** RH, not just tent RH, and alert above 60 %.
3. **Smell and pests.** Carbon filters on exhaust if needed. Soil pots bring fungus gnats; consider bottom-watering and sticky traps.
4. **Noise.** Air pumps and inline fans run 24/7 inside the house. Choose quiet models and put pumps on foam pads.
5. **Fire.** Lights and electrical loads in fabric tents. Use a **smoke detector in the grow area** (interconnected with the house if possible) and no daisy-chained power strips.
6. **Light leaks and schedules.** Each tent has its own photoperiod.
7. **WiFi in the basement.** Confirm signal strength where the nodes will sit. The Pi should use Ethernet if a cable is nearby.

## 4. Phases

Each phase ends with a working, useful system. **Do not start a phase until the previous one meets its "done when" criteria.**

### Phase 0 — Foundations ✅ built
- Repo skeleton (`backend/`, `frontend/`, `firmware/`, `deploy/`, `simulator/`, `docs/`; `hardware/` already holds the printable node enclosure).
- Pi setup script: 64-bit Raspberry Pi OS Lite, SSD boot, Docker, Tailscale.
- `docker-compose.yml` with Mosquitto, backend and ESPHome dashboard.
- Backend skeleton: config loading (tents/zones/devices from `config.yaml`), SQLite migrations, MQTT client, health endpoint.
- Frontend skeleton: layout, navigation, WebSocket connection, °F/°C setting.
- **Simulator**: fakes N tent nodes + the water node over MQTT in ESPHome topic format, reacting to commands (lights ON → tent temp rises, exhaust ON → RH falls).
- **Done when:** `docker compose --profile sim up` on a laptop shows live fake data for 3 tents on a dashboard.
- **Status:** done and verified in Docker. Not yet done: running `deploy/pi-setup.sh` on the real Pi.

### Phase 1 — Monitor (software built; waiting on hardware)

Built and tested against the simulator: history storage and charts, alert rules, ntfy phone
notifications, multi-board node firmware (config-validated only), the USB board detector,
GUI auto-discovery, and the build guide with wiring diagrams ([BUILD.md](BUILD.md)).

**Not done until hardware exists:** flashing real nodes, and the "done when" test below.
Deferred to Phase 2 because they need control: the "lights commanded on but dark" alert and
the interlock alerts. Not built: custom date ranges on the History page.

Soil pots: moisture sensing is built (firmware, per-sensor calibration in the GUI, dashboard,
history, "Soil dry" alert). Four pots are assumed to be in tent 2 until the layout is decided.

- `tent<N>` nodes: air temp/RH (SHT45), light level (BH1750), RTC (DS3231), leak sensor.
- `tent3` (tower tent) also reads the tower reservoir level and temperature.
- `water` node: RDWC reservoir temp, reservoir level floats, leak sensor(s), **room** temp/RH.
- Backend stores readings, downsamples them, and evaluates alert rules.
- GUI: Dashboard (per tent + room), History charts, Alerts, System Health.
- Alerts: leak, reservoir low, tent too hot/cold, room RH high, node offline, sensor stale.
- **Done when:** one week of real data, and a deliberately triggered leak alert (wet the sensor) reaches both phones within 30 s.

### Phase 2 — Control (software built; waiting on hardware)

Built and tested against the simulator: node firmware for lights, exhaust, water heater,
pumps, top-off and soil watering with every interlock (compiled for the ESP32 DevKit, logic
unit-tested natively); hub control with timed manual modes, settings, the latched leak
alarm and automatic soil watering; the Controls page; output wiring diagrams.

**Design change from the original plan:** schedules run on the nodes all the time instead
of on the Pi with a node fallback copy. There is now one implementation of each behaviour,
and it keeps working with the Pi off.

**Not done:** nothing has run on real hardware, so the "done when" test below is only
proven in simulation. No tent heater (I-6). Device on/off history is not charted yet.

- Relay boxes connected to node GPIOs: lights and exhaust fan per tent, water heater, RDWC + air pumps, tower pump, top-off pump.
- Node-local water thermostat with a setpoint pushed from the Pi. Node-local tent exhaust control on temp/RH thresholds.
- Pi schedules: per-tent photoperiod, tower pump cycle.
- Manual override for each device: `AUTO` / `ON` / `OFF`, with an optional expiry.
- **Soil watering:** one small 12 V pump per pot from a plain-water tank, driven by the tent's node through a MOSFET board. Dose-based auto-watering per pot plus a "water now" button, with every limit in SAFETY.md §4b. Watering log on the soil chart.
- Fallback mode on the nodes when the Pi heartbeat is lost. All interlocks in SAFETY.md implemented **on the nodes**.
- **Done when:** unplugging the Pi for 30 minutes leaves lights on schedule, exhaust and water heat regulating and pumps cycling, and wetting a leak sensor stops every water pump within seconds.

### Phase 3 — Water chemistry and calibration (software built; waiting on hardware)

Decision: **cheap hobby sensors throughout** (this is a home garden, not a business). The
system is built around their limits: see HARDWARE.md §3.

Built and tested against the simulator:
- Firmware for an analog pH kit and an analog TDS/EC board in the control bucket, with the EC board powered only while it is read (compiled for the ESP32 DevKit).
- A general **calibration system** in the GUI (System page): pH against 2–3 buffers, EC against one solution, soil dry/wet, and optional temperature/humidity offsets. The hub captures each point itself once the reading is steady, corrects EC for water temperature, and reminds you when pH or EC calibration is due.
- pH and EC on the dashboard, a Water page, history charts, and out-of-range alerts (limits in `config.yaml`).
- A **dosing log** for what you add by hand, shown as markers on the pH and EC charts.
- A grow **journal**: plants, where they are, days growing, notes and photos.
- Air sensor choice per node: SHT4x, AHT20 or BME280.

**Not done:** nothing has run on real probes. Per-crop target profiles (limits are one set of
alert rules for now). pH is not temperature-compensated (the error is small at room temperature).

- **Done when:** a week of pH/EC readings that agree with a handheld meter to within about 0.2 pH and 10 % EC.

### Phase 4 — Dosing (software built; waiting on hardware)

Built and tested against the simulator:
- `dosing` node firmware: four peristaltic pumps with millilitre limits enforced on the node (compiled for the ESP32 DevKit, logic unit-tested natively).
- Hub dosing logic with three modes, **OFF by default**: `SUGGEST` (you approve each dose) and `AUTO`, which must be turned on explicitly through a warning with Cancel / Continue.
- Pump priming and flow-rate calibration, manual dose buttons, a lockout with a "re-enable" step, and alerts for a waiting suggestion and for stopped dosing.
- Every limit in SAFETY.md §4, including the stricter rules for cheap probes.

**Not done:** nothing has run on real pumps or probes. The dose sizes and the pH/EC targets in
`config.yaml` are cautious starting values, not tuned for your reservoir.

- **Done when:** two weeks in `SUGGEST` mode whose suggestions you agree with, then `AUTO` for a week without hitting a limit.

### Phase 5 — Extras (pick and choose)
- Pi/USB cameras per tent: snapshots, timelapse.
- CO₂ sensor (SCD41) per tent.
- Power monitoring per circuit (PZEM-004T or metering smart plugs) and electricity cost tracking.
- Variable-speed exhaust (0–10 V or PWM inline fans) instead of on/off.
- Dimmable lights with sunrise/sunset.
- Richer journal: harvest weights, crop profiles, reminders.
- Data export (CSV).

## 5. Open questions / TBD

- [ ] **Which strawberry tower** (height and width) → tower tent size. Which crops go in each 4×4.
- [ ] **Basement winter temperature and humidity**: measure for a few days (a $10 hygrometer is fine).
- [ ] **Existing dehumidifier?** If buying one, pick a model that resumes running after a power loss.
- [ ] **Floor type** (carpet, LVP, tile, concrete) and whether there's a floor drain.
- [ ] **Basement circuits**: which outlets share a breaker, and what else is on them.
- [ ] **Grow light wattage**: measure with a plug-in watt meter.
- [ ] **Number of DWC buckets** and the control bucket's volume.
- [ ] **WiFi strength** where the tents will be. Is Ethernet available for the Pi?
- [ ] **Old tablet: make, model and OS version**.
- [x] **Budget**: cheap hobby sensors throughout.
