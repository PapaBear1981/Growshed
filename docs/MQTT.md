# MQTT Topic Spec

The nodes run ESPHome, so the topics follow **ESPHome's default MQTT layout** with
`topic_prefix: growshed/<node>`. The backend adapts to ESPHome, not the other way around.

## Node topics (published by ESPHome)

```
growshed/<node>/status                         online | offline   (birth / last-will, retained)
growshed/<node>/sensor/<id>/state              numeric value as string, in SI units
growshed/<node>/binary_sensor/<id>/state       ON | OFF
growshed/<node>/switch/<id>/state              ON | OFF
growshed/<node>/switch/<id>/command            ON | OFF           (backend → node)
growshed/<node>/number/<id>/state              numeric
growshed/<node>/number/<id>/command            numeric            (backend → node, setpoints)
growshed/<node>/text_sensor/<id>/state         string
growshed/<node>/climate/<id>/...               ESPHome thermostat topics
```

Nodes: `tent1`, `tent2`, `tent3` (tower tent), … `tentN`, `water`, `dosing`.

## Required diagnostic entities per node

| Entity | Type | Meaning |
|---|---|---|
| `mode` | text_sensor | `normal` / `fallback` |
| `last_interlock` | text_sensor | ID + timestamp of the latest interlock (e.g. `I-4`), or empty |
| `wifi_rssi` | sensor | dBm |
| `uptime` | sensor | seconds |
| `heartbeat_age` | sensor | seconds since the last hub heartbeat |
| `board` | text_sensor | Board type, e.g. `ESP32-S3 DevKitC` (from the board profile) |
| `firmware` | text_sensor | ESPHome version |

Each switchable device also gets `<device>_source` (text_sensor): `auto`, `manual`, `fallback` or `interlock`.

## Auto-discovery

The hub listens to `growshed/#`, so any board that publishes under `growshed/<new-id>/...`
appears in the GUI by itself: on the System page (with its board type) and as a dashed
"new device" card on the dashboard showing its raw readings. Zones, alerts and history only
apply once its entities are added to `config/config.yaml`.

On/off entities (`binary_sensor`, `switch`) are published only when they change. The GUI
therefore trusts them for as long as their node is alive (any message within 120 s and not
`offline`), instead of judging each one by its own age.

## Hub topics (published by backend)

```
growshed/hub/heartbeat     unix timestamp, every 30 s (not retained)
growshed/hub/status        online | offline   (LWT, retained)
growshed/hub/leak_alarm    ON | OFF  (retained; ON if ANY node reports a leak, cleared only by a human in the GUI)
```

Nodes subscribe to `growshed/hub/heartbeat` (no heartbeat for > 180 s → FALLBACK) and to
`growshed/hub/leak_alarm` (ON → interlock I-10). Nodes also act on their **own** leak sensors
directly, without MQTT.

## Entity IDs (initial)

| Node | Sensors | Binary sensors | Switches / numbers |
|---|---|---|---|
| tent*N* | `air_temp`, `air_rh`, `light_lux`, `soil_1..n`, (`co2`) | `leak` | `lights`, `exhaust_fan`, (`heater`); numbers `light_on_minute`, `light_off_minute`, `max_temp`, `max_rh`, (`heat_setpoint`) |
| tent3 (tower tent) adds | `tower_temp` | `tower_low` | `tower_pump`; numbers `tower_on_s`, `tower_off_s` |
| water | `res_temp`, `room_temp`, `room_rh`, `ph`, `ec` | `res_low`, `res_high`, `topoff_tank_low`, `leak_res`, `leak_topoff` | `water_heater`, `air_pump`, `rdwc_pump`, `top_off`; number `water_setpoint` |
| dosing | — | `leak` | `dose_ph_down`, `dose_ph_up`, `dose_a`, `dose_b` (commands are **mL amounts** via `number`; the node converts mL → run time with a hard timeout) |

## Control (Phase 2)

```
growshed/<node>/select/<dev>_mode/state        auto | on | off
growshed/<node>/select/<dev>_mode/command      auto | on | off      (hub → node)
growshed/<node>/text_sensor/<dev>_source/state auto | manual | fallback | interlock
                                               (dose pumps: idle | dosing | refused)
growshed/<node>/number/<setting>/command       new value            (hub → node)
growshed/<node>/dose/<dev>/command             seconds to run       (hub → node, not retained)
growshed/<node>/text_sensor/last_interlock/state   e.g. "I-4 lights"
growshed/hub/leak_alarm                        ON | OFF  (retained)
```

- **Relays are never switched directly.** `switch/<dev>/state` reports the relay; commands sent to `switch/<dev>/command` are ignored by the node. The hub asks for a *mode*, and the node's control loop applies its interlocks before anything moves.
- Mode devices: `lights`, `exhaust_fan` (every tent), `tower_pump` (tent3), `water_heater`, `air_pump`, `rdwc_pump` (water).
- Dose pumps: `top_off` (water), `water_1..4` (tent2). The node caps the run time, enforces a rest and a daily cap, and refuses during a leak, with an empty tank or full reservoir, or without the hub.
- Settings (`number`): `light_on_minute`, `light_off_minute`, `max_temp`, `max_rh` (tents), `tower_on_s`, `tower_off_s` (tent3), `water_setpoint` (water). Stored on the node.

## Simulator-only topics

```
growshed/sim/<node>/fault     leak on|off, sensor_fail on|off, offline, online,
                              tower_low on|off (tent3), drain (water),
                              soil_dry, soil_water, soil_unplug, soil_replug,
                              tank_low on|off (tent2)
```

Real nodes ignore these. They exist so alerts and interlocks can be tested with no hardware.

## Rules

- **Soil moisture (`soil_N`) is published as raw volts.** The hub converts to percent with a per-sensor two-point calibration (air = 0 %, water = 100 %) and stores the raw volts, so recalibrating also corrects history. An uncalibrated sensor has no value.

- **Binary sensors are ON when the named condition is true**: `leak` ON = wet, `res_low` ON = level is low, `res_high` ON = full.
- A sensor that fails to read publishes `nan`. The backend stores that as "no value", never as a number.

- Units on the wire are **SI**: °C, %RH, lux, ppm, pH, µS/cm, mL, seconds.
- Setpoint and schedule `number` entities use `restore_value: true` so they survive node reboots.
- The backend never assumes a command succeeded. The `.../state` echo is the source of truth.
- Mosquitto requires authentication. No anonymous access.
