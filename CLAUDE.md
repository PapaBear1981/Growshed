# CLAUDE.md — instructions for coding agents

This repo is a controller for an indoor hydroponics garden (grow tents in a finished basement). It is **vibe coded**: the owners
direct and test, the AI writes the code. Optimize for **correctness, safety and readability**
over cleverness.

## Read first
1. `docs/PLAN.md`: phases, decisions, current scope
2. `docs/SAFETY.md`: **non-negotiable** rules (interlocks, fallbacks, dosing limits)
3. `docs/ARCHITECTURE.md`: components, data model, pages
4. `docs/MQTT.md`: topic contract between nodes and backend
5. `docs/HARDWARE.md`: parts and power budget

## Golden rules
- **Never weaken, bypass or remove anything in SAFETY.md.** If a request conflicts with it, stop and say so.
- **Interlocks and fallbacks live on the ESP32 nodes (ESPHome)**, not only on the Pi. The Pi must never be safety-critical.
- Work **one phase at a time**, in order. Don't build Phase N+1 features early.
- Everything above the nodes must run on a laptop with the **simulator**, with no hardware.
- Units are **SI internally and on MQTT**. Convert only in the frontend display layer.
- Timestamps are UTC epoch seconds in storage. Use local time only for schedules and display.
- Prefer boring, well-known libraries. Ask before adding a new dependency.
- Keep files small and modules focused. Write docstrings explaining *why* for any control logic.

## Stack
- `firmware/`: ESPHome YAML, one file per node (`tent1.yaml`, `tent2.yaml`, `tent3.yaml`, `water.yaml`, `dosing.yaml`) sharing `common/` packages (tent nodes share one tent package). Secrets in `firmware/secrets.yaml` (gitignored).
- `backend/`: Python 3.11+, FastAPI, aiomqtt, SQLite (WAL), pytest. Formatting: ruff.
- `frontend/`: Svelte + Vite, uPlot for charts. Conservative browser target (old Android tablet). Touch targets ≥ 44 px.
- `deploy/`: docker-compose (mosquitto, backend, esphome), Pi setup script.
- `simulator/`: fake nodes over MQTT that also react to commands.
- `hardware/enclosure/`: 3D-printable node enclosure (OpenSCAD source + exported STLs). Re-export the STLs whenever the `.scad` changes.

## Definition of done (every task)
- Backend: `pytest` passes; `ruff check` is clean. New control/alert/dosing logic has unit tests, including failure cases.
- Frontend: `npm run build` succeeds; the page works at phone width and tablet width.
- Firmware: `esphome config firmware/<node>.yaml` validates.
- End-to-end: `docker compose up` + simulator shows the feature working.
- Docs updated if behavior, topics or the data model changed.

## Never commit
`.env`, `firmware/secrets.yaml`, SQLite databases, photos, or any credentials.
