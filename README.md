# Growshed

Monitoring and control for an indoor hydroponics garden in grow tents in a finished basement:
RDWC, Kratky, a strawberry tower and soil pots. A Raspberry Pi 4 hub runs the web GUI, history
and alerts. ESP32 nodes running ESPHome handle sensors, relays and local failsafes.

**Status:** Phase 0 (foundations) is built: the hub, a live dashboard and a simulator that
stands in for the hardware. The software for Phase 1 (history, alerts,
phone notifications, soil sensors), Phase 3 (pH/EC with cheap probes, sensor calibration,
dosing log, grow journal), Phase 4 (pH and nutrient dosing pumps, off by default) and Phase 2 (control of lights, fans, heater and pumps,
automatic soil watering, safety cutoffs on the nodes) is built too. It has only run against
the simulator so far; no real node has been built yet. See [the plan](docs/PLAN.md) for what comes next.

## Try it on a laptop (no hardware needed)

Requires Docker.

```bash
cp .env.example .env
```

```bash
docker compose --profile sim up -d --build
```

Open <http://localhost:8000>. You should see three tents, the reservoir and the basement with
live (simulated) readings. Stop it with `docker compose --profile sim down`.

### Poke the simulator

Fake a problem by publishing to `growshed/sim/<node>/fault` (nodes: `tent1`, `tent2`, `tent3`,
`water`). For example, a leak in tent 1 (use the node password from your `.env`):

```bash
docker compose exec mosquitto mosquitto_pub -u node -P change-me-node -t growshed/sim/tent1/fault -m "leak on"
```

Faults: `leak on|off`, `sensor_fail on|off`, `offline`, `online`; `tower_low on|off` (tent3);
`drain` (water); `soil_dry`, `soil_water`, `soil_unplug`, `soil_replug`, `tank_low on|off` (tent2); `ph_buffer 7|off`, `ec_solution 1413|off`, `ph_set 7.4`,
`ec_set 500` (water); `empty ph_down`, `refill ph_down` (dosing). Ask a node for a device mode the way the hub does (`auto`, `on` or `off`):

```bash
docker compose exec mosquitto mosquitto_pub -u node -P change-me-node -t growshed/tent2/select/lights_mode/command -m on
```

## On the Raspberry Pi

See [deploy/README.md](deploy/README.md).

## Development

```bash
pip install -r backend/requirements-dev.txt
```

```bash
pytest && ruff check .
```

```bash
cd frontend && npm install && npm run build
```

Run the pieces without Docker: a local Mosquitto broker, then
`cd backend && uvicorn growshed.main:app --factory`, `python -m simulator` from the repo root,
and `cd frontend && npm run dev` for live-reloading GUI work.

## Documentation

- [Plan & phases](docs/PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Safety rules](docs/SAFETY.md)
- [Hardware & power budget](docs/HARDWARE.md)
- [MQTT topic spec](docs/MQTT.md)
- [Building the nodes: wiring diagrams and assembly](docs/BUILD.md)
- [Node firmware, supported boards and flashing](firmware/README.md)
- [Printable node enclosure](hardware/enclosure/README.md)
- [Instructions for coding agents](CLAUDE.md)
