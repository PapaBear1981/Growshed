# Safety Rules

This system puts water, mains electricity, lights and pumps inside a **finished basement of an
occupied house**, often unattended. **These rules are requirements, not suggestions.** Code
changes must never weaken them without an explicit decision recorded in this file.

## 1. Physical

- Every outlet feeding the grow area is **GFCI-protected** (GFCI receptacle, GFCI breaker, or plug-in GFCI adapter).
- Map the basement circuits. Keep continuous load ≤ 80 % of each breaker (≤ 1,440 W on 15 A). See HARDWARE.md §1.
- No daisy-chained power strips. Mains is switched only by **pre-built, enclosed relay outlet boxes** rated for the load.
- **Spill containment:** every reservoir, bucket and the tower stands in a tray that can hold its full volume. Tents have waterproof floor liners.
- **Leak sensors:** at least one per tent, plus one under the control bucket and one under the top-off tank.
- **Top-off comes from a tank/jug, never directly from house plumbing.**
- Electronics sit above the water line, in enclosures, with drip loops on every cable.
- **Smoke detector** in the grow area.
- Keep room humidity in check (dehumidifier) to protect the drywall and flooring.

## 2. Node fallback behavior (Pi heartbeat lost > 3 min)

| Device | Fallback behavior |
|---|---|
| Lights (each tent) | Built-in photoperiod from the node RTC (last known schedule, default 06:00–22:00) |
| Exhaust fan (each tent) | Local thermostat/humidistat: ON above the tent max temp or max RH (last known setpoints) |
| Tent heater (if installed) | Keep regulating to the last known setpoint |
| Water heater | Keep regulating to the last known setpoint (default 20 °C / 68 °F) |
| Air pump(s) | **ON** (always) |
| RDWC circulation pump | **ON** (always) |
| Tower pump | Built-in cycle (default 15 min ON / 45 min OFF, lights-on hours only) |
| Top-off | **OFF** (never refill unattended without the Pi) |
| Dosing pumps | **OFF** (never dose without the Pi) |

Air pumps and the RDWC pump should be wired to the **normally-on** outlet of their relay box,
so a dead node or a loose signal wire leaves them running.

## 3. Interlocks (enforced on the node, always, even in manual ON)

| ID | Rule |
|---|---|
| I-1 | **Water heater OFF** if the reservoir low-float reads LOW (dry-fire protection) |
| I-2 | **Water heater OFF** if water temp > 26 °C (79 °F) |
| I-3 | **Water heater OFF** on water temp sensor failure (the heater's own thermostat is the backup). Alert |
| I-4 | **Tent lights OFF** if tent air temp > 35 °C (95 °F) for > 2 min. Auto-restore when < 30 °C. Alert |
| I-5 | **Exhaust fan ON** if tent air temp > 30 °C (86 °F) or on tent sensor failure |
| I-6 | **Tent heater OFF** (if installed) if tent air temp > 30 °C or on sensor failure. (A house basement doesn't freeze, so failing OFF is safe) |
| I-7 | **Tower pump OFF** if the tower reservoir is low |
| I-8 | **RDWC pump OFF** if the control-bucket low-float reads LOW for > 10 s |
| I-9 | **Top-off OFF** if the high-float trips, any leak sensor is wet, or the pump has run > configured max (default 120 s) per fill |
| I-10 | **Any leak sensor wet → every water-moving pump and the top-off OFF on every node** (leak state is shared over MQTT, *and* each node also acts on its own local leak sensors without needing MQTT). Air pumps stay ON. A human must clear it in the GUI |

Whenever an interlock takes control, the node publishes the event, the Pi shows the
state source as `interlock`, and an alert is sent.

> Cross-node note for I-10: a node can only act on another node's leak sensor while MQTT is
> up. So **every node that controls a water pump must have its own leak sensor** in its tray.

## 4. Dosing limits (Phase 4)

Enforced on **both** the Pi (controller) and the dosing node (hard cap).

- Max single dose per pump: configurable, default **2 mL** (scale to reservoir volume).
- Max per pump per 24 h: default **20 mL**. On hitting it: lockout + alert, and a human must reset it.
- After any dose, wait at least **15 min** with circulation running before measuring again or dosing again.
- Never dose pH up and pH down within the same hour.
- Don't dose if: a probe calibration is > 60 days old, a reading is stale or noisy, circulation is off, the level is low, or a leak alarm is active.
- Nutrient A and B are dosed in **equal amounts, A first, with a gap of ≥ 60 s**.
- Each dosing pump runs for at most `ceil(max_dose / ml_per_sec) + 1` seconds per command (hard timeout on the node).
- Concentrated acids/bases are stored in their own spill tray, away from electronics.

## 5. Alerts that must exist

- **Leak detected (any sensor): critical**, repeated every 5 min until acknowledged.
- Reservoir low, tower reservoir low: critical.
- Tent air temp > 30 °C (86 °F) or < 15 °C (59 °F): warning. Interlock I-4 fired: critical.
- Tent RH > 75 % for > 30 min: warning.
- **Room (basement) RH > 60 % for > 1 h: warning** (mold risk to the house).
- Water temp < 16 °C or > 24 °C: warning.
- Lights commanded ON but the lux sensor reads dark (or vice versa): warning (bulb/driver/relay failure).
- Node offline > 5 min, any node in FALLBACK: warning.
- Sensor stale > 10 min: warning.
- Pi itself down: an external "dead man's switch" (e.g. healthchecks.io ping from the Pi every 5 min) so that silence also alerts you.
