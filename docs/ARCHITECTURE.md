# Architecture

## 1. Overview

```
   Phone / laptop / wall tablet (browser, kiosk mode on tablet)
                     │  HTTP + WebSocket (via LAN or Tailscale)
                     ▼
┌────────────────────────────────────────────────────────────┐
│ Raspberry Pi 4 — "hub"                                     │
│  ┌──────────────┐  ┌───────────────────────────────────┐   │
│  │ Mosquitto    │◄─┤ Backend (FastAPI, asyncio)        │   │
│  │ MQTT broker  │  │  • ingest: MQTT → SQLite          │   │
│  └──────▲───────┘  │  • controller: schedules, modes,  │   │
│         │          │    overrides, setpoints           │   │
│         │          │  • alerts → ntfy                  │   │
│         │          │  • REST API + WebSocket           │   │
│         │          │  • serves built frontend          │   │
│         │          └───────────────────────────────────┘   │
│         │          ┌───────────────────────────────────┐   │
│         │          │ ESPHome dashboard (flash / OTA)   │   │
│         │          └───────────────────────────────────┘   │
└─────────┼──────────────────────────────────────────────────┘
          │ MQTT over WiFi
   ┌──────┼──────────────┬─────────────────────┬──────────────────┐
   ▼      ▼              ▼                     ▼                  ▼
 tent1 node        tent2..N nodes        water node          dosing node (Phase 4)
 (ESP32/ESPHome)                         (ESP32/ESPHome)     (ESP32/ESPHome)
  air T/RH, lux,                          reservoir T, pH, EC, 4× peristaltic pumps
  RTC, leak, soil                         levels, leaks,
  → lights, exhaust                       room T/RH
    fan, (heater)                         → water heater, air
  (tower tent node also:                    pump, RDWC pump,
   tower level/temp → tower pump)           top-off
```

## 2. Responsibilities: who decides what

The key design rule: **the Pi is the brain, but it is never safety-critical.**
If the Pi, the WiFi or the broker dies, each node keeps the plants alive on its own.

| Concern | Lives on | Notes |
|---|---|---|
| Interlocks (dry-heater cutoff, overtemp, leak, overflow) | **Node** | Always enforced, even under manual override. See SAFETY.md |
| All automation: light schedule, exhaust limits, water thermostat, tower pump cycle | **Node** | Runs all the time from settings stored on the node, with or without the hub (`firmware/common/control.h`) |
| Fallback | **Node** | Same automation; manual modes are ignored and doses refused while the hub is silent |
| Changing settings (light times, limits, setpoints) | Pi | Range-checked, then stored on the node |
| Manual modes and their expiry | Pi | Asks the node for auto/on/off; reverts to auto when the timer runs out |
| House-wide leak alarm (I-10) | Pi + node | The Pi latches it and tells every node; each node also acts on its own leak sensor |
| Soil watering decisions | Pi | Dose-based, with the limits in SAFETY.md §4b. The node enforces run time, rest, daily cap, tank and leak |
| Dosing decisions | Pi | Node enforces per-dose and per-day maximums (SAFETY.md §4) |
| History, charts, alerts, journal, calibration records | Pi | |

### Node operating modes
- **NORMAL**: the Pi heartbeat has been seen within the last 3 minutes. The node obeys commands, and interlocks still apply.
- **FALLBACK**: no heartbeat for over 3 minutes. The node runs its built-in fallback behavior (SAFETY.md §2) and publishes `mode=fallback`. It returns to NORMAL on the next heartbeat.

## 3. Backend modules (`backend/`)

| Module | Purpose |
|---|---|
| `config` | Loads `config.yaml` (tents/zones, nodes, devices, sensors, circuits, alert thresholds) + env vars |
| `db` | SQLite schema and migrations (Alembic or simple numbered SQL files) |
| `mqtt` | `aiomqtt` client. Subscribes to `growshed/#` and publishes commands and heartbeat |
| `ingest` | Parses ESPHome state topics → typed readings → live state, recorder and WebSocket broadcast. (Phase 2: aggregates leak state → `growshed/hub/leak_alarm`) |
| `recorder` | Buffers and stores numeric readings; 5-minute and hourly rollups; retention; history queries on a shared time grid |
| `notify` | ntfy delivery and the optional dead man's ping (standard library only) |
| `calibration` | Calibration for soil (dry/wet), pH (2–3 buffers, fitted line), EC (one solution, temperature-corrected) and optional temperature/humidity offsets. Captures points itself once readings are steady. Applied to live values, history output and therefore alerts |
| `journal` | Manual dosing log, plants, notes and photos (record-keeping only) |
| `background` | The periodic loop: alert ticks, notification retries, flush, rollup, pruning |
| `control` | Device modes (auto/on/off + expiry), node settings, dose requests, the latched leak alarm |
| `watering` | Automatic soil watering per pot: soak wait, response check, strike lockout, daily cap |
| `alerts` | Rule evaluation (threshold, on/off, node offline, fallback, silent sensor) with hold and clear delays, acknowledge, repeats, restart recovery |
| `dosing` | pH and nutrient dosing: OFF / SUGGEST / AUTO, trust checks on readings, mixing wait, response check, lockouts, pump flow calibration |
| `api` | REST routes + `/ws` WebSocket for live updates |
| `journal` | Plants, notes, photos, harvests |

## 4. Data model (target)

Tables are added by numbered migrations as each phase needs them. Built so far: `setting`
(Phase 0); `series`, `reading`, `reading_5m`, `reading_1h`, `alert_event`, `calibration` (Phase 1); `device_override`, `dose_event`, `watering_pot` (Phase 2); `calibration_point` (replacing `calibration`), `dose_log`, `plant`, `journal_entry` (Phase 3); `chem_dose` (Phase 4). Readings
are keyed by a `series` row per MQTT entity instead of the `sensor` table sketched below, and
alert rules live in `config.yaml`, not in an `alert_rule` table.

```
zone(id, name, kind[tent|room|rdwc|kratky|tower|soil], parent_zone_id)  -- systems live inside tents
node(id, name, last_seen, rssi, firmware, mode)
sensor(id, node_id, zone_id, key, kind, unit_si, display_name, enabled)
reading(ts, sensor_id, value)                  -- raw, kept 30 days
reading_5m(ts, sensor_id, min, max, avg)       -- kept 1 year
reading_1h(ts, sensor_id, min, max, avg)       -- kept forever
device(id, node_id, zone_id, key, kind[heater|light|pump|fan|valve|doser], circuit, watts, display_name)
device_state(device_id, ts, on, source[auto|manual|fallback|interlock])
device_mode(device_id, mode[auto|on|off], expires_at)
schedule(id, device_id, kind[daily_window|cycle], params_json, enabled)
setpoint(key, value_si, updated_at)
alert_rule(id, sensor_id|node_id, kind, params_json, severity, enabled)
alert_event(id, rule_id, started_at, ended_at, acked_at, message)
calibration(id, sensor_id, ts, kind, points_json, notes)
dose(id, ts, product, ml, source[manual|auto], reason)
plant(id, zone_id, name, variety, started_at, ended_at, notes)
journal_entry(id, plant_id, ts, text, photo_path)
setting(key, value)                            -- e.g. display_units=imperial
```

All `ts` values are UTC epoch seconds. Readings are written in batches. The SQLite DB
runs in WAL mode.

## 5. Frontend (`frontend/`)

Svelte 4 + Vite, built to static files that the backend serves. (Svelte 4, not 5: version 5's
runtime needs newer browsers than the old tablet may have.) Live data comes over one
WebSocket. Charts use uPlot.

**Old-tablet constraint:** set the Vite build target conservatively (decide once the
tablet model is known; assume Chrome ~80 / Safari 13 until then). Keep animations light,
and make all touch targets ≥ 44 px. The tablet runs in kiosk mode (e.g. Fully Kiosk
Browser on Android) and should keep the screen awake.

Pages:
1. **Dashboard**: one card per tent + a room card + the reservoir card, with current values, colored green/amber/red against targets, device on/off chips, active alerts banner, node mode (NORMAL/FALLBACK).
2. **Controls**: each device with AUTO/ON/OFF + "for N hours", current state, the source of that state (auto/manual/fallback/interlock), and setpoints.
3. **Schedules**: light photoperiod, pump cycles, fan cycles.
4. **History**: multi-sensor charts with 6h/24h/7d/30d/custom ranges, and device on/off bands overlaid (e.g. lights/exhaust vs tent temperature).
5. **Water**: pH/EC/temp/level trends, dosing log (manual entry now, auto later), calibration wizards.
6. **Alerts**: active + history, acknowledge, rule thresholds editor.
7. **Journal**: plants, notes, photos.
8. **System**: node health, Pi health (CPU temp, disk, uptime), units setting, backup/export.

## 6. Deployment (`deploy/`)

- `docker-compose.yml` (repo root): `mosquitto` and `backend` (also serves the frontend) always; `simulator` with `--profile sim`; `esphome` (dashboard on port 6052) with `--profile esphome`.
- Mosquitto runs with username/password auth: users `backend` and `node`, passwords from a `.env` file that is not committed. The broker's password file is rebuilt from `.env` on every start.
- Persistent volumes: `data/` (SQLite, photos), `mosquitto/`, `esphome/` (node YAML lives in the repo under `firmware/` and is mounted).
- Nightly SQLite backup (`.backup` command) to a second location.
- `pi-setup.sh`: OS packages, Docker, Tailscale, hardware watchdog enabled, log rotation.

## 7. Development without hardware

Everything above the nodes must be buildable and testable on a laptop:
- `docker compose --profile sim up` (or `python -m simulator` against any broker) produces realistic fake readings (day/night temperature swings, slowly drifting pH, a level that drops and gets topped off).
- The simulator also obeys commands (lights ON → tent temperature rises, exhaust ON → tent RH falls), and can inject faults (leak, stuck sensor, node offline), so control and alert logic can be tested end-to-end.
- Backend unit tests cover the controller, alerts and dosing logic (pytest).
