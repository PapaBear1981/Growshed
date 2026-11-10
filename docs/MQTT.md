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

Each switchable device also gets `<device>_source` (text_sensor): `auto`, `manual`, `fallback` or `interlock`.

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

## Rules

- Units on the wire are **SI**: °C, %RH, lux, ppm, pH, µS/cm, mL, seconds.
- Setpoint and schedule `number` entities use `restore_value: true` so they survive node reboots.
- The backend never assumes a command succeeded. The `.../state` echo is the source of truth.
- Mosquitto requires authentication. No anonymous access.
