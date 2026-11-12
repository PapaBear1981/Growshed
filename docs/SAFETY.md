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
| Soil watering pumps | **OFF** (never water unattended without the Pi). Potted plants tolerate a day or two dry; a pump with nobody watching can flood the floor |
| Dosing pumps | **OFF** (never dose without the Pi) |

Air pumps and the RDWC pump should be wired to the **normally-on** outlet of their relay box,
so a dead node or a loose signal wire leaves them running.

### How this is built (Phase 2)

Every automatic behaviour runs **on the node, all the time**, from settings stored on the
node (light times, fan limits, water setpoint, pump cycle). The hub only changes those
settings and asks for modes (auto / on / off) or doses. So NORMAL and FALLBACK use the same
automation; in FALLBACK the node additionally ignores manual on/off modes and refuses
top-off and watering doses. The decision logic is one function, `gs::decide` in
`firmware/common/control.h`, with native unit tests in `firmware/tests/`.

## 3. Interlocks (enforced on the node, always, even in manual ON)

| ID | Rule |
|---|---|
| I-1 | **Water heater OFF** if the reservoir low-float reads LOW (dry-fire protection) |
| I-2 | **Water heater OFF** if water temp > 26 °C (79 °F) |
| I-3 | **Water heater OFF** on water temp sensor failure (the heater's own thermostat is the backup). Alert |
| I-4 | **Tent lights OFF** if tent air temp > 35 °C (95 °F) for > 2 min. Auto-restore when < 30 °C. Alert |
| I-5 | **Exhaust fan ON** if tent air temp > 30 °C (86 °F) or on tent sensor failure |
| I-6 | **Tent heater OFF** (if installed) if tent air temp > 30 °C or on sensor failure. (A house basement doesn't freeze, so failing OFF is safe.) *Not implemented: no tent heater exists in the firmware or config yet. It must be added together with this rule.* |
| I-7 | **Tower pump OFF** if the tower reservoir is low |
| I-8 | **RDWC pump OFF** if the control-bucket low-float reads LOW for > 10 s |
| I-9 | **Top-off OFF** if the high-float trips, any leak sensor is wet, or the pump has run > configured max (default 120 s) per fill |
| I-10 | **Any leak sensor wet → every water-moving pump and the top-off OFF on every node** (leak state is shared over MQTT, *and* each node also acts on its own local leak sensors without needing MQTT). Air pumps stay ON. A human must clear it in the GUI |
| I-11 | **Each soil watering pump runs for at most its configured dose time per command** (default 20 s, hard timeout on the node), then must rest at least 10 min |
| I-12 | **Soil watering pumps OFF** if the watering tank's low float reads LOW (protects the pump and stops it sucking air) |

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
- Don't dose if: the pH calibration is > 30 days old or the EC calibration is > 90 days old (the limits the hub already uses for its "calibration is due" reminders; cheap probes drift), a reading is stale or noisy, circulation is off, the level is low, or a leak alarm is active.
- **Cheap probes:** with hobby-grade pH and EC probes, auto-dosing must default to `SUGGEST` mode (a person approves each dose), and `AUTO` must also refuse to act on a reading that jumped by more than 0.5 pH or 30 % EC since the previous one.
- Nutrient A and B are dosed in **equal amounts, A first, with a gap of ≥ 60 s**.
- Each dosing pump runs for at most `ceil(max_dose / ml_per_sec) + 1` seconds per command (hard timeout on the node).
- Concentrated acids/bases are stored in their own spill tray, away from electronics.

### How dosing is built (Phase 4)

- **Three modes, default OFF.** `SUGGEST`: the hub proposes one small dose and a person approves it in the GUI; everything is re-checked at the moment of approval. `AUTO`: the hub doses by itself. The GUI shows a warning with Cancel / Continue before switching to `AUTO`, and the hub itself refuses the switch unless the request says the warning was accepted.
- **No mode other than OFF** until all four pumps have a measured flow rate and both probes are calibrated.
- **The hub never acts on a reading it cannot trust:** fewer than 3 readings in the last 5 minutes, readings that disagree (more than 0.3 pH or 15 % EC apart), a sudden jump (more than 0.5 pH or 30 % EC between two readings: 15 minutes of distrust), stale readings, or an overdue calibration.
- **A dose must show an effect.** After the 15-minute mixing wait the hub compares the reading with the one before the dose. Two doses of the same kind with no movement in the right direction stop all dosing until a person re-enables it.
- **Nutrient B follows A after 60 seconds.** If B cannot be dosed (leak, node offline), dosing stops and says the mix is uneven.
- **The dosing node enforces its own limits** whatever it is told (`gs::MlDoser` in `firmware/common/control.h`): 2 mL per dose, 20 mL per pump per day, a 5-minute rest per pump, one pump at a time, no pH up within an hour of pH down (or the reverse), a 60-second ceiling on any run, nothing during a leak or without the hub, and no dosing at all from a pump whose flow rate was never measured. The hub's limits in `config.yaml` cannot be set above the node's.
- **Priming** (filling a tube, measuring flow) runs a pump for at most 30 seconds and is not counted as a dose. The outlet must be in a measuring cup, never the reservoir.
- Nothing is ever diluted automatically: if pH or EC overshoots, a person deals with it.

## 4b. Automatic soil watering limits (Phase 2)

Decided when soil-pot support was added. Watering pumps are **not built yet**; these rules
bind the Phase 2 implementation. Enforced on **both** the Pi (controller) and the node (hard cap).

The dangerous failure is a moisture sensor that reads "dry" forever (pulled out of the pot,
unplugged, failed) while the pump keeps answering it. So:

- Water in **small fixed doses**, never "until the sensor says wet". After a dose, wait at least **30 min** for the water to soak in before judging again.
- **The reading must respond.** If a pot's moisture has not risen after **2 consecutive doses**, stop auto-watering that pot and alert ("watered but soil did not get wetter": empty tank, kinked tube, or the sensor is out of the soil). A human must re-enable it.
- Max doses per pot per 24 h: default **6**. On hitting it: lockout + alert.
- No auto-watering if the pot's sensor is uncalibrated, stale, or reading outside its calibrated range by more than 10 %.
- No watering while any leak alarm is active (I-10) or the watering tank is low (I-12).
- Modes per pot: `OFF` (the default) / `AUTO`, plus a manual "water now" button. A manual dose obeys the leak alarm, the tank-low check, the 30-minute soak wait and the daily cap. It does not need a calibrated sensor or a dry reading: a person is choosing to water.
- Every pot stands in a saucer or tray, and the tent's leak sensor sits where overflow would collect.
- The watering tank holds **plain water** and is separate from the nutrient reservoirs. Its outlet tubes end **above** the tank's water level at the pot, or have anti-siphon valves, so a stopped pump cannot keep siphoning.

## 4c. What can and cannot be changed from the GUI

The Settings page can change alert limits, dosing targets, dose sizes and watering
thresholds. Every value is range-checked by the hub (`backend/growshed/tunables.py`). Dose
sizes cannot be set above `max_dose_ml`, which cannot be set above the node's own cap, and
the two pH dosing limits must stay at least 0.4 pH apart. **None of the interlocks in §3, the
fallback behaviour in §2, or the node-side dose caps can be changed from the GUI**: they live
in the firmware and need a deliberate reflash.

Quiet hours hold back **warnings** only. Critical alerts (leaks, low reservoirs) are always
sent at once.

## 5. Alerts that must exist

- **Leak detected (any sensor): critical**, repeated every 5 min until acknowledged.
- Reservoir low, tower reservoir low: critical.
- Tent air temp > 30 °C (86 °F) or < 15 °C (59 °F): warning. Interlock I-4 fired: critical.
- Tent RH > 75 % for > 30 min: warning.
- **Room (basement) RH > 60 % for > 1 h: warning** (mold risk to the house).
- Water temp < 16 °C or > 24 °C: warning.
- Soil moisture below the configured limit for 30 min: warning.
- Lights commanded ON but the lux sensor reads dark (or vice versa): warning (bulb/driver/relay failure).
- Node offline > 5 min, any node in FALLBACK: warning.
- Sensor stale > 10 min: warning.
- Pi itself down: an external "dead man's switch" (e.g. healthchecks.io ping from the Pi every 5 min) so that silence also alerts you.
