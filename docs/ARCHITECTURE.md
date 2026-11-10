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
   ┌──────┼────────────────┬─────────────────────┐
   ▼      ▼                ▼                     ▼
 climate node          water node          dosing node (Phase 4)
 (ESP32/ESPHome)       (ESP32/ESPHome)     (ESP32/ESPHome)
  air T/RH, outdoor T,  reservoir T, pH, EC,  4× peristaltic pumps
  lux, RTC, door        levels, leak
  → heater, lights,     → water heater, air
    fans, humidity        pump, RDWC pump,
                          tower pump, top-off
```

## 2. Responsibilities: who decides what

The key design rule: **the Pi is the brain, but it is never safety-critical.**
If the Pi, the WiFi or the broker dies, each node keeps the plants alive on its own.

| Concern | Lives on | Notes |
|---|---|---|
| Interlocks (dry-heater cutoff, overtemp, leak, overflow) | **Node** | Always enforced, even under manual override. See SAFETY.md |
| Air and water thermostats (closed loop) | **Node** | ESPHome `thermostat` climate component. Setpoints come from the Pi and persist in node flash |
| Fallback schedules (lights, tower pump) | **Node** | Run only when the Pi heartbeat is lost |
| Normal schedules, photoperiod, pump cycles | Pi | Sends ON/OFF commands |
| Manual overrides and expiries | Pi | Expired overrides revert to AUTO |
| Dosing decisions | Pi | Node enforces per-dose and per-day maximums (SAFETY.md §4) |
| History, charts, alerts, journal, calibration records | Pi | |

### Node operating modes
- **NORMAL**: the Pi heartbeat has been seen within the last 3 minutes. The node obeys commands, and interlocks still apply.
- **FALLBACK**: no heartbeat for over 3 minutes. The node runs its built-in fallback behavior (SAFETY.md §2) and publishes `mode=fallback`. It returns to NORMAL on the next heartbeat.

## 3. Backend modules (`backend/`)

| Module | Purpose |
|---|---|
| `config` | Loads `config.yaml` (devices, sensors, zones, alert thresholds) + env vars |
| `db` | SQLite schema and migrations (Alembic or simple numbered SQL files) |
| `mqtt` | `aiomqtt` client. Subscribes to `growshed/#` and publishes commands and heartbeat |
| `ingest` | Parses ESPHome state topics → typed readings → DB + WebSocket broadcast |
| `controller` | Device modes (AUTO/ON/OFF + expiry), schedules, setpoint publishing, heartbeat |
| `alerts` | Rule evaluation (threshold, stale, offline, rate-of-change), dedupe/ack, ntfy delivery |
| `dosing` | Phase 4. Dosing state machine with limits |
| `api` | REST routes + `/ws` WebSocket for live updates |
| `journal` | Plants, notes, photos, harvests |
| `simulator` | Standalone script that fakes nodes over MQTT for hardware-free development |

## 4. Data model (initial)

```
zone(id, name, kind[air|rdwc|kratky|tower|soil])
node(id, name, last_seen, rssi, firmware, mode)
sensor(id, node_id, zone_id, key, kind, unit_si, display_name, enabled)
reading(ts, sensor_id, value)                  -- raw, kept 30 days
reading_5m(ts, sensor_id, min, max, avg)       -- kept 1 year
reading_1h(ts, sensor_id, min, max, avg)       -- kept forever
device(id, node_id, zone_id, key, kind[heater|light|pump|fan|valve|doser|humidity], display_name)
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

Svelte + Vite, built to static files that the backend serves. Live data comes over one
WebSocket. Charts use uPlot.

**Old-tablet constraint:** set the Vite build target conservatively (decide once the
tablet model is known; assume Chrome ~80 / Safari 13 until then). Keep animations light,
and make all touch targets ≥ 44 px. The tablet runs in kiosk mode (e.g. Fully Kiosk
Browser on Android) and should keep the screen awake.

Pages:
1. **Dashboard**: zone cards with current values, colored green/amber/red against targets, device on/off chips, active alerts banner, node mode (NORMAL/FALLBACK).
2. **Controls**: each device with AUTO/ON/OFF + "for N hours", current state, the source of that state (auto/manual/fallback/interlock), and setpoints.
3. **Schedules**: light photoperiod, pump cycles, fan cycles.
4. **History**: multi-sensor charts with 6h/24h/7d/30d/custom ranges, and device on/off bands overlaid (e.g. heater duty vs temperature).
5. **Water**: pH/EC/temp/level trends, dosing log (manual entry now, auto later), calibration wizards.
6. **Alerts**: active + history, acknowledge, rule thresholds editor.
7. **Journal**: plants, notes, photos.
8. **System**: node health, Pi health (CPU temp, disk, uptime), units setting, backup/export.

## 6. Deployment (`deploy/`)

- `docker-compose.yml`: `mosquitto`, `backend` (also serves the frontend), `esphome` (dashboard on port 6052).
- Mosquitto runs with username/password auth (nodes and backend each get credentials from a `.env` file that is not committed).
- Persistent volumes: `data/` (SQLite, photos), `mosquitto/`, `esphome/` (node YAML lives in the repo under `firmware/` and is mounted).
- Nightly SQLite backup (`.backup` command) to a second location.
- `pi-setup.sh`: OS packages, Docker, Tailscale, hardware watchdog enabled, log rotation.

## 7. Development without hardware

Everything above the nodes must be buildable and testable on a laptop:
- `docker compose up` + `python -m simulator` produces realistic fake readings (day/night temperature swings, slowly drifting pH, a level that drops and gets topped off).
- The simulator also obeys commands (e.g. heater ON → simulated temperature rises), so control logic can be tested end-to-end.
- Backend unit tests cover the controller, alerts and dosing logic (pytest).
