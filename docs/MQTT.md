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
growshed/<node>/climate/<id>/...               ESPHome thermostat topics (mode, target temp, action)
```

Nodes: `climate`, `water`, `dosing`.

## Required diagnostic entities per node

| Entity | Type | Meaning |
|---|---|---|
| `mode` | text_sensor | `normal` / `fallback` |
| `last_interlock` | text_sensor | ID + timestamp of the latest interlock (e.g. `I-1`), or empty |
| `wifi_rssi` | sensor | dBm |
| `uptime` | sensor | seconds |
| `heartbeat_age` | sensor | seconds since the last hub heartbeat |

Each switchable device also gets `<device>_source` (text_sensor): `auto`, `manual`, `fallback` or `interlock`.

## Hub topics (published by backend)

```
growshed/hub/heartbeat     unix timestamp, every 30 s (not retained)
growshed/hub/status        online | offline   (LWT, retained)
```

Nodes subscribe to `growshed/hub/heartbeat`. Without one for > 180 s they enter FALLBACK.

## Entity IDs (initial)

| Node | Sensors | Binary sensors | Switches / numbers |
|---|---|---|---|
| climate | `air_temp`, `air_rh`, `outdoor_temp`, `light_lux`, (`co2`) | `door_open` | `heater`, `lights`, `exhaust_fan`, `circ_fan`, `humidity_device`; numbers `heat_setpoint`, `light_on_minute`, `light_off_minute` |
| water | `res_temp`, `tower_temp`, `ph`, `ec`, `soil_1..n` | `res_low`, `res_high`, `tower_low`, `leak` | `water_heater`, `air_pump`, `rdwc_pump`, `tower_pump`, `top_off`; numbers `water_setpoint`, `tower_on_s`, `tower_off_s` |
| dosing | — | — | `dose_ph_down`, `dose_ph_up`, `dose_a`, `dose_b` (commands are **mL amounts** via `number`, not raw ON/OFF; the node converts mL → run time with a hard timeout) |

## Rules

- Units on the wire are **SI**: °C, %RH, lux, ppm, pH, µS/cm, mL, seconds.
- Setpoint `number` entities use `restore_value: true` so they survive node reboots.
- The backend never assumes a command succeeded. The `.../state` echo is the source of truth.
- Mosquitto requires authentication. No anonymous access.
