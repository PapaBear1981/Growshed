# Growshed — Project Plan

A controller for a winter hydroponics garden in an uninsulated wooden backyard shed.
It monitors and controls the water, air temperature, humidity, lights, air pumps,
heaters and (later) nutrient dosing. The GUI works on phones, a laptop and a
wall-mounted old tablet.

Read with: [ARCHITECTURE.md](ARCHITECTURE.md), [SAFETY.md](SAFETY.md),
[HARDWARE.md](HARDWARE.md), [MQTT.md](MQTT.md).

---

## 1. What we're growing and how

| System | Description | Automation level |
|---|---|---|
| **RDWC** | One central "control" bucket (reservoir) feeding several DWC buckets, with a return pump | Fully monitored. Water heat, air and top-off are controlled. pH/EC is monitored now and auto-dosed later |
| **Kratky** | Passive jars/totes, no pumps | Monitoring only (optional level/temp) |
| **Strawberry tower** | Vertical tower with its own small reservoir and a pump on a cycle timer | Pump cycles, level monitoring |
| **Soil pots** | Ordinary potted plants | Moisture sensing, hand watering |

## 2. Decisions made

| Topic | Decision | Reason |
|---|---|---|
| Brain | Raspberry Pi 4 (8GB), booting from a **USB SSD** | SD cards die under constant database writes |
| Field nodes | **ESP32 boards running ESPHome** | Declarative YAML, proven sensor drivers, OTA updates, native MQTT. Much less hand-written code in the safety-critical layer, which matters for a vibe-coded project |
| Messaging | MQTT (Mosquitto on the Pi) | Standard and debuggable. Matches ESPHome's MQTT conventions |
| Backend | Python 3.11+, FastAPI, asyncio, `aiomqtt`, SQLite | Readable and needs no extra servers |
| Frontend | Svelte + Vite (static build) + **uPlot** charts | Small bundles and fast charts. Must run on an **old tablet** |
| Mains switching | **Pre-built relay outlet boxes** (Digital Loggers IoT Power Relay or equivalent), driven by ESP32 GPIO | No DIY mains wiring. The ESP32 can switch loads with the Pi down |
| Heat | Oil-filled radiator (air) + titanium aquarium heater in the control bucket (water) | Oil radiators are the safest common choice. Their thermal mass suits on/off control |
| Power | Two heavy-gauge outdoor extension cords from **two different house circuits** | Heater gets its own circuit (see HARDWARE.md §1) |
| Dosing | Manual for now. Auto-dosing in Phase 4 | Bad auto-dosing kills plants overnight |
| GUI devices | Phone, laptop, old tablet in kiosk mode | One responsive web app serves all three |
| Remote access | Tailscale (no router port-forwarding) | Secure and zero-config |
| Alerts | ntfy push notifications (ntfy.sh or self-hosted on the Pi) | Free and works on Android and iOS |
| Units | Stored internally in **SI (°C, µS/cm, mL, L)**. Displayed in **°F** by default (user setting) | One canonical unit avoids conversion bugs |

## 3. The big physical issue: insulation

The shed is uninsulated wood. Rough estimate for an ~8×10×8 ft shed:

- Uninsulated (~R-1 walls/roof): heat loss is about **450 BTU/hr per °F** of indoor/outdoor difference, before drafts.
- A 1500 W oil radiator puts out about **5,100 BTU/hr**, which holds only about **10–15 °F above outdoor temperature**.
- 1" rigid foam board (R-5) on walls and ceiling plus weatherstripping cuts losses roughly **5×**. The same heater could then hold about **50 °F+ above outside**.
- The grow lights add useful heat while they're on.

**Recommendation:** foam-board the walls and ceiling, put something under the floor, and seal the gaps before winter. That will matter more than anything in the code. The system will log indoor vs outdoor temperature and heater duty cycle, so you'll see exactly how well the shed holds heat.

## 4. Phases

Each phase ends with a working, useful system. **Do not start a phase until the previous one meets its "done when" criteria.**

### Phase 0 — Foundations
- Repo skeleton (`backend/`, `frontend/`, `firmware/`, `deploy/`, `docs/`).
- Pi setup script: 64-bit Raspberry Pi OS Lite, SSD boot, Docker, Tailscale.
- `docker-compose.yml` with Mosquitto, backend and ESPHome dashboard (for flashing nodes).
- Backend skeleton: config loading, SQLite migrations, MQTT client, health endpoint.
- Frontend skeleton: layout, navigation, WebSocket connection, °F/°C setting.
- **Simulator**: a script that publishes fake sensor data over MQTT in ESPHome topic format, so the backend and GUI can be built and tested with no hardware.
- **Done when:** `docker compose up` on a laptop + simulator shows live fake data on a dashboard.

### Phase 1 — Monitor
- `climate` node: air temp/RH (SHT45), outdoor temp (DS18B20), light level (BH1750), RTC (DS3231).
- `water` node: reservoir temp (DS18B20), reservoir level (floats), tower reservoir level, floor leak sensor.
- Backend stores readings, downsamples them, and evaluates alert rules.
- GUI: Dashboard, History charts, Alerts, System Health (node online/offline, WiFi RSSI, last-seen).
- Alerts: freeze risk, reservoir low, leak, node offline, sensor stale.
- **Done when:** one week of real data in the charts, and a deliberately triggered alert (e.g. probe in ice water) reaches both phones.

### Phase 2 — Control
- Relay outlet boxes connected to node GPIOs (heater, water heater, lights, fans, tower pump, air pump, humidity device).
- Node-local thermostats for air heat and water heat, with setpoints pushed from the Pi.
- Pi schedules: light photoperiod, tower pump cycle, fan cycles.
- Manual override for each device: `AUTO` / `ON` / `OFF`, with an optional expiry ("off for 2 hours").
- Fallback mode on the nodes when the Pi heartbeat is lost (see SAFETY.md).
- All interlocks in SAFETY.md implemented **on the nodes**.
- **Done when:** unplugging the Pi for 30 minutes leaves the heaters regulating, lights on schedule and pumps cycling, and the GUI shows what happened once the Pi is back.

### Phase 3 — Water chemistry (manual dosing)
- Atlas Scientific EZO pH + EC with isolated carriers in the control bucket.
- Guided **calibration wizards** in the GUI (pH 4/7/10, EC dry/low/high), recording calibration dates.
- Target ranges per crop profile. Out-of-range alerts.
- **Dosing log**: you record manual doses (what, how much, when) and see them on the pH/EC charts.
- Grow journal (basic): plants, location, start date, notes, photos.
- **Done when:** a week of stable pH/EC readings that agree with a handheld meter, and manual doses show on the chart.

### Phase 4 — Auto dosing
- `dosing` node: 4 peristaltic pumps (pH down, pH up, nutrient A, nutrient B), 12 V, MOSFET-driven.
- Pump calibration (mL/second) wizard.
- Dosing controller on the Pi: small doses, a mixing wait, re-measure, repeat. Strict limits (see SAFETY.md §4).
- Modes: `OFF` / `SUGGEST` (tells you what it would dose; you approve in the GUI) / `AUTO`.
- **Done when:** two weeks in `SUGGEST` mode whose suggestions you agree with, then `AUTO` for a week without hitting a limit.

### Phase 5 — Extras (pick and choose)
- Pi camera: periodic photos, timelapse, live snapshot in the GUI.
- CO₂ sensor (SCD41) and humidity/CO₂-driven exhaust.
- Power monitoring for each circuit (PZEM-004T) and cost tracking.
- Light sunrise/sunset, if dimmable lights are ever added.
- Richer grow journal: harvest weights, crop profiles, reminders ("change reservoir water", "recalibrate pH").
- Data export (CSV).

## 5. Open questions / TBD

- [ ] **Location / typical winter lows**: decides the heater/insulation plan and alert thresholds.
- [ ] **Shed dimensions**: refines the heat-loss estimate.
- [ ] **Grow light wattage**: measure with a plug-in watt meter. Needed for the circuit budget (HARDWARE.md §1).
- [ ] **Number of DWC buckets** and the control bucket's volume.
- [ ] **Does the strawberry tower have its own reservoir?** (Assumed yes.)
- [ ] **Old tablet: make, model and OS version**: decides the frontend browser target.
- [ ] **Budget**: mainly decides Atlas (lab grade) vs cheaper pH/EC probes.
- [ ] Will the plugs at the house end of the extension cords be GFCI-protected? (They must be. See SAFETY.md.)
