# Safety Rules

This system combines water, mains electricity, heaters and an unattended building.
**These rules are requirements, not suggestions.** Code changes must never weaken them
without an explicit decision recorded in this file.

## 1. Electrical (physical)

- Both extension cords plug into **GFCI-protected** outlets at the house end, or use inline GFCI cords.
- Use **12 AWG outdoor-rated (SJTW/SJOOW) cords**, one continuous length each. No daisy-chaining, no light-duty power strips.
- **Circuit A (heat):** the oil radiator only, plus nothing else of significant load.
  Many radiator manuals advise against extension cords. A short, heavy 12 AWG cord is the
  mitigation. The long-term fix is a proper outdoor circuit installed by an electrician.
- **Circuit B (everything else):** keep continuous load ≤ 80% of the breaker (≤ 1,440 W on a 15 A circuit). See HARDWARE.md §1.
- Mains is switched only by **pre-built, enclosed relay outlet boxes** rated for the load. No open relay modules on 120 V.
- Electronics sit above the water line, in enclosures, with drip loops on every cable.
- Use a floor **leak sensor** under the reservoirs.

## 2. Node fallback behavior (Pi heartbeat lost > 3 min)

| Device | Fallback behavior |
|---|---|
| Air heater | Keep regulating to the last known setpoint (default 15 °C / 59 °F) |
| Water heater | Keep regulating to the last known setpoint (default 20 °C / 68 °F) |
| Air pump(s) | **ON** (always) |
| RDWC circulation pump | **ON** (always) |
| Lights | Built-in photoperiod from the node RTC (default 06:00–22:00) |
| Tower pump | Built-in cycle (default 15 min ON / 45 min OFF, lights-on hours only) |
| Fans | Circulation fan ON. Exhaust only under the humidity/overtemp rules below |
| Top-off valve | **OFF** (never refill unattended without the Pi) |
| Dosing pumps | **OFF** (never dose without the Pi) |

Air pumps and circulation pumps should be wired to the **normally-on** outlet of their
relay box, so a dead node or a disconnected signal wire leaves them running.

## 3. Interlocks (enforced on the node, always, even in manual ON)

| ID | Rule |
|---|---|
| I-1 | **Water heater OFF** if the reservoir low-float reads LOW (dry-fire protection) |
| I-2 | **Water heater OFF** if water temp > 26 °C (79 °F) |
| I-3 | **Air heater OFF** if air temp > 32 °C (90 °F) |
| I-4 | **Air heater: sensor failure** (no valid reading for 2 min) → heater relay **ON** and the radiator's own thermostat dial regulates. Alert. *(In winter a dead sensor must not cause a freeze. The radiator dial is set as the backup regulator.)* |
| I-5 | **Water heater: sensor failure** → **OFF**, alert (the aquarium heater's own thermostat is the backup) |
| I-6 | **Tower pump OFF** if the tower reservoir is low |
| I-7 | **RDWC pump OFF** if the control-bucket low-float reads LOW for > 10 s |
| I-8 | **Top-off OFF** if the high-float trips, the leak sensor is wet, or the valve has run > configured max (default 120 s) per fill |
| I-9 | **All pumps + top-off OFF** if the floor leak sensor is wet. Air pumps stay ON |
| I-10 | **Exhaust fan ON** if air temp > 30 °C (86 °F) |

Whenever an interlock takes control, the node publishes the event, the Pi shows the
state source as `interlock`, and an alert is sent.

## 4. Dosing limits (Phase 4)

Enforced on **both** the Pi (controller) and the dosing node (hard cap).

- Max single dose per pump: configurable, default **2 mL** (scale to reservoir volume).
- Max per pump per 24 h: default **20 mL**. On hitting it: lockout + alert, and a human must reset it.
- After any dose, wait at least **15 min** with circulation running before measuring again or dosing again.
- Never dose pH up and pH down within the same hour.
- Don't dose if: a probe calibration is > 60 days old, a reading is stale or noisy, circulation is off, the level is low, or a leak alarm is active.
- Nutrient A and B are dosed in **equal amounts, A first, with a gap of ≥ 60 s**.
- Each dosing pump runs for at most `ceil(max_dose / ml_per_sec) + 1` seconds per command (hard timeout on the node).

## 5. Alerts that must exist

- Air temp < 7 °C (45 °F): warning. < 3 °C (37 °F): **critical** (freeze risk).
- Water temp < 16 °C or > 24 °C: warning.
- Reservoir low, tower reservoir low, leak detected: critical.
- Node offline > 5 min, any node in FALLBACK: warning.
- Sensor stale > 10 min: warning.
- Heater ON continuously > 2 h with air temp still falling: warning (heater failed, or not enough heat).
- Pi itself down: use an external "dead man's switch" (e.g. healthchecks.io ping from the Pi every 5 min) so that silence also alerts you.
