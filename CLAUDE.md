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
- `frontend/`: **Svelte 4** (not 5) + Vite, uPlot for charts. No `gap` on flexbox, `inset`, or `aspect-ratio` in CSS. Conservative browser target (old Android tablet). Touch targets ≥ 44 px.
- `docker-compose.yml` (root) + `deploy/`: mosquitto, backend, and the `sim` / `esphome` profiles; Pi setup script.
- `config/config.yaml`: zones, nodes, sensors, devices, alert rules. Adding a tent is a config change.
- `firmware/boards/`: one profile per supported board (chip + pin names). Node packages use only the pin names, never raw GPIO numbers. Validate every node against every profile when changing shared packages.
- `tools/`: setup helpers (`python -m tools.detect_boards`, `python -m tools.wiring_diagrams`). Standard library only.
- `docs/wiring/*.svg` are generated from the board profiles by `python -m tools.wiring_diagrams`. Regenerate and update `docs/BUILD.md` whenever a pin, sensor or node role changes (a test fails if they are stale).
- `firmware/common/control.h`: the node control and interlock logic, pure C++, unit-tested natively by `firmware/tests/control_test.cpp` (run by `pytest`). Change the tests with it. `simulator/control.py` is its Python port: keep the two in step.
- The hub never switches a relay. It asks a node for a mode, a setting or a dose (`backend/growshed/control.py`); only the node's control loop drives outputs.
- `simulator/`: fake nodes over MQTT that mirror the firmware's modes, interlocks and dose limits.
- `hardware/enclosure/`: 3D-printable node enclosure (OpenSCAD source + exported STLs). Re-export the STLs whenever the `.scad` changes.

## Definition of done (every task)
- Backend: `pytest` and `ruff check .` pass (run both from the repo root). New control/alert/dosing logic has unit tests, including failure cases.
- Frontend: `npm run build` succeeds; the page works at phone width and tablet width.
- Firmware: `esphome config firmware/<node>.yaml` validates, and any change to a lambda or `control.h` also passes `esphome compile` for at least the affected node (use the `ghcr.io/esphome/esphome:stable` Docker image).
- End-to-end: `docker compose --profile sim up -d --build` shows the feature working in a browser.
- Docs updated if behavior, topics or the data model changed.

## Never commit
`.env`, `firmware/secrets.yaml`, SQLite databases, photos, or any credentials.
