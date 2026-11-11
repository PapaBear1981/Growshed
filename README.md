# Growshed

Monitoring and control for an indoor hydroponics garden in grow tents in a finished basement:
RDWC, Kratky, a strawberry tower and soil pots. A Raspberry Pi 4 hub runs the web GUI, history
and alerts. ESP32 nodes running ESPHome handle sensors, relays and local failsafes.

**Status:** Phase 0 (foundations) is built: the hub, a live dashboard and a simulator that
stands in for the hardware. Phase 1 is under way: multi-board node firmware and automatic
detection of new boards exist; history and alerts do not yet. See [the plan](docs/PLAN.md) for what comes next.

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
`drain` (water). Switch a device the way the hub will in Phase 2:

```bash
docker compose exec mosquitto mosquitto_pub -u node -P change-me-node -t growshed/tent2/switch/lights/command -m ON
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
- [Node firmware, supported boards and wiring](firmware/README.md)
- [Printable node enclosure](hardware/enclosure/README.md)
- [Instructions for coding agents](CLAUDE.md)
