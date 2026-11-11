# Building the nodes

How to wire, solder and test the four sensor nodes for **Phase 1 (monitoring)**. Nothing here
touches mains power: everything runs from a USB charger at 5 V and 3.3 V. Relay wiring is
added in Phase 2.

> These instructions and diagrams match the firmware's pin assignments (a test keeps the
> diagrams in sync), but **no node has been built from them yet**. Test each sensor on the
> bench as described before mounting anything, and report anything that doesn't behave as
> written.

## 1. What you are building

| Node | Lives | Measures | Diagram |
|---|---|---|---|
| `tent1` | Outside tent 1 | Air temperature, humidity, light, floor leak | [tent node](wiring/tent-node.svg) |
| `tent2` with soil pots | Outside tent 2 | The same as a tent node, plus soil moisture for up to 4 pots | [tent node with soil pots](wiring/tent-soil-node.svg) |
| `tent3` | Outside the tower tent | The same, plus tower water temperature and tower reservoir level | [tower tent node](wiring/tower-tent-node.svg) |
| `water` | Next to the RDWC control bucket | Water temperature, reservoir low/full, two leak sensors, basement air | [water node](wiring/water-node.svg) |

The diagrams are drawn for the **ESP32 DevKit (WROOM-32)**. For another board, the pin for
each signal is in the table in [`firmware/README.md`](../firmware/README.md), or redraw them:

```bash
python -m tools.wiring_diagrams --board esp32-s3 --out my-diagrams
```

## 2. Parts

Per node:

| Part | tent1 / tent2 | tent3 | water | Notes |
|---|---|---|---|---|
| ESP32 DevKit + screw-terminal breakout board | 1 | 1 | 1 | Buy the breakout that matches your DevKit's pin count (30 or 38) |
| USB charger (1 A or more) + USB cable | 1 | 1 | 1 | A data-capable cable; charge-only cables can't flash |
| Air temperature/humidity board: SHT40/41/45, AHT20 or BME280 | 1 | 1 | 1 | Set the matching `air:` line in the node file. The steps below say SHT45; the others wire the same way |
| BH1750 light sensor board | 1 | 1 | — | |
| DS3231 clock module + CR2032 battery | 1 | 1 | — | |
| Leak sensor module (see below) | 1 | 1 | 2 | |
| DS18B20 waterproof probe | — | 1 | 1 | The stainless-steel kind on a cable |
| 4.7 kΩ resistor | — | 1 | 1 | |
| Vertical float switch | — | 1 | 2 | |
| Printed enclosure | 1 | 1 | 1 | [`hardware/enclosure/`](../hardware/enclosure/README.md) |

Soil pots add one **capacitive soil moisture sensor** per pot (the black "v1.2" or "v2.0" kind
with no exposed metal; the cheap two-prong metal ones corrode within weeks).

**Buy the I²C sensors with STEMMA QT / Qwiic connectors if you can** (Adafruit and SparkFun
sell the SHT45, BH1750 and DS3231 this way). They plug together with ready-made cables, so
there is almost no soldering, and the cable colours match the diagrams: red 3.3 V, black
ground, blue SDA, yellow SCL. You need one "STEMMA QT to bare wires" cable per node to reach
the screw terminals, and short QT-to-QT cables to chain the sensors.

**Leak sensor module:** use the common "rain / water sensor" kit: a flat sensing plate plus a
small board with a blue adjustment knob and pins labelled `VCC`, `GND`, `DO`, `AO`. The firmware
also works with two bare wires as a probe (one to the input, one to ground), but that only
triggers reliably in fairly conductive water. Nutrient solution is; clean top-off water may
not be. The module is the safer choice.

Tools and supplies: soldering iron and solder, wire strippers, small screwdriver, multimeter,
22 AWG stranded hook-up wire in several colours, 4-conductor cable for the sensor runs,
heat-shrink tubing, zip ties, a label maker or tape and a marker. Wire ferrules are a
nice-to-have for the screw terminals.

## 3. Soldering tips (if you're new to it)

- **Never solder to the ESP32 itself.** It plugs into the breakout board; all wires go to screw terminals.
- You only solder two kinds of thing: **header pins onto sensor boards** that come without them, and **wire extensions** (probe leads, float switch leads).
- Header pins: push the pins into a breadboard, sit the sensor board on top, and solder there. The breadboard holds everything square.
- Heat the pad and the pin together for a second or two, *then* feed solder in. A good joint is a small shiny cone, not a ball.
- Joining two wires: slide heat-shrink on **first**, twist the stripped ends together, solder, slide the heat-shrink over and shrink it.
- Tin the stripped end of every stranded wire (or crimp a ferrule) before it goes into a screw terminal, so no stray strand can touch the neighbouring terminal.
- Unplug the USB cable before changing any wiring.

## 4. Test on the bench first

Do this for each node before anything goes in an enclosure.

1. Plug the ESP32 into its breakout board. Wire **one** sensor following the diagram, leads kept short.
2. Flash the node ([`firmware/README.md`](../firmware/README.md#flashing-a-node)).
3. Open the node's log in the ESPHome dashboard. At boot it lists the I²C devices it found:

   | Address | Device |
   |---|---|
   | `0x44` | SHT40 / SHT41 / SHT45 |
   | `0x38` | AHT20 |
   | `0x76` | BME280 |
   | `0x23` | BH1750 |
   | `0x68` | DS3231 |

   A device missing from the list is a wiring problem (see Troubleshooting).
4. Open the Growshed dashboard. The node's card should show live values.
5. Add the next sensor, power up again, and repeat.

Check that each sensor reacts:

| Sensor | Do this | Expect |
|---|---|---|
| SHT45 | Breathe on it | Humidity jumps, temperature rises slightly |
| BH1750 | Cover it with your hand, then shine a phone light on it | Light drops to near 0, then rises |
| Leak module | Touch a wet fingertip across the plate | "Floor leak" turns **WET** within a second and the card turns red. Dry it: back to **Dry** after ~10 s |
| DS18B20 | Hold the metal tip in your fist | Temperature climbs toward ~30 °C / 86 °F |
| Low float | Let the float hang down, then lift it | **LOW** when hanging, **OK** when lifted (after 5 s) |
| Full float | Lift the float | **Full** when lifted |
| Soil sensor | Hold it in air, then stand it in a glass of water up to the line | On the System page the voltage drops by about a volt in water. Calibrate it there (below) |

**If a float reads backwards:** most float switches can be reversed. Pull off the retaining
clip, turn the float upside down, and put it back.

**Leak module adjustment:** turn the blue knob until the board's second LED is off when the
plate is dry and comes on with a single drop of your actual water on the plate.

### Soil moisture sensors

1. **Protect the electronics.** The small components at the top of the sensor must stay dry. Cover that end with heat-shrink tubing or a few coats of clear nail varnish, leaving the long blade bare.
2. Wire `VCC` to 3V3, `GND` to GND and `AOUT` to the pot's analog terminal (see the diagram). The lead can be a few metres long.
3. **Calibrate before planting it.** Open the System page, find the sensor under *Soil sensor calibration*, and follow the two steps there: *Set dry* with the sensor in open air, *Set wet* with it standing in a glass of water up to the printed line. Until both are done the pot shows "not calibrated".
4. Push the sensor into the soil up to the line, about halfway between the stem and the pot's edge, and don't move it afterwards: moving it changes the reading.
5. Water the pot normally and watch the number for a few days. Note the reading when the plant actually needs water, then set the "Soil dry" limit in `config/config.yaml` to match (it starts at 30 %).

## 5. Assemble a node

1. **Print and prepare the enclosure.** Screw the breakout board to the standoffs. The DS3231 clock goes inside the box (foam tape).
2. **Plan the cable slots**, left to right. Suggested: USB power, I²C cable into the tent, leak sensor, then (tent3 / water) temperature probe and float switches. Leave two slots free for the Phase 2 relay signal wires.
3. **I²C sensors** (SHT45, BH1750): one 4-conductor cable from the node into the tent, then chain from the first sensor to the second. Keep the total cable under about **2 m (6 ft)**. Longer I²C runs become unreliable.
4. **Leak module:** the small board stays in the enclosure; its two-wire lead to the sensing plate can be extended several metres. Lay the plate flat, face up, at the lowest point of the spill tray.
5. **DS18B20** (tent3, water): red to 3V3, black to GND, yellow to the 1-Wire terminal. Put the **4.7 kΩ resistor** between the 3V3 terminal and the 1-Wire terminal: both legs go into the same terminals as the probe's red and yellow wires. Without it the probe reads nothing.
6. **Float switches:** two wires, no polarity. One to the input terminal, one to GND.
7. **Sharing terminals:** several wires land on 3V3 and on GND. Either twist-and-tin them into one ferrule, or use a lever connector (Wago-style) as a splitter: one wire to the terminal, the rest into the connector.
8. **Strain relief:** lay each cable over the bar behind the slots and zip-tie it. Tug gently on every cable from outside; nothing inside should move.
9. **Label both ends** of every cable (`tent1 leak`, `res LOW`…).
10. Close the lid, mount the box **outside the tent with the slots facing down**, and leave a drip loop in every cable (a low point below the box, so water runs off the cable instead of into it).

## 6. Final checks, node installed

- [ ] The dashboard card shows every reading, and none are greyed out.
- [ ] The System page shows the node **online**, mode **normal**, and a WiFi signal better than about −75 dBm.
- [ ] Wet the leak plate: the card turns red and both phones get a notification.
- [ ] Float switches read correctly with the reservoir actually full and actually low.
- [ ] Unplug the node: a "Node offline" alert arrives within about 5 to 7 minutes. Plug it back in.
- [ ] The SHT45 is shaded from the grow light (direct light makes it read warm).

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Node never appears on the dashboard | Wrong WiFi or MQTT details in `secrets.yaml`; a charge-only USB cable; the Pi's address changed |
| An I²C device is missing from the boot scan | SDA and SCL swapped; no power to that board; cable too long; a cold solder joint on its header |
| No I²C devices found at all | SDA or SCL shorted to something, or both swapped at the terminals |
| Temperature/humidity shows `—` | That sensor isn't answering: same checks as above |
| DS18B20 shows `—` | Missing 4.7 kΩ resistor, or yellow and black swapped |
| Leak always **WET** | Knob set too sensitive, plate dirty or damp, or `DO` shorted to ground |
| Leak never trips | Knob set too insensitive; `DO` not connected (the firmware reads an unconnected input as dry) |
| Float reads backwards | Flip the float (section 4) |
| Node keeps restarting | Weak USB charger or a short on the 3.3 V line: unplug sensors one at a time |
| Readings freeze but the node is online | A "Sensor not reporting" alert follows after 10 minutes; check that sensor's wiring |

## 8. Phase 2: wiring the outputs

Do this only after the node's sensors work. Output diagrams:
[tent1](wiring/tent-outputs.svg), [tent2 with soil pots](wiring/tent-soil-outputs.svg),
[tower tent](wiring/tower-tent-outputs.svg), [water node](wiring/water-outputs.svg).

**Mains safety.** The node only ever touches the relay boxes' low-voltage signal terminals.
Never open a relay box, plug every box into a GFCI outlet, and keep the boxes off the floor
and away from the reservoirs.

### Relay outlet boxes (lights, fans, heater, 120 V pumps)

1. Each box has a two-terminal signal input marked `+` and `-`. Run a two-conductor wire from the node: the output terminal to `+`, GND to `-`. Polarity matters.
2. Plug the load into the right kind of outlet on the box:
   - **Normally OFF** for lights, exhaust fans, the water heater and the tower pump: off unless the node says on.
   - **Normally ON** for the air pump and the circulation pump: they run unless the node says off, so they keep running if the node dies.
3. Label each box with what it switches and which node output drives it.

### 12 V pumps (soil watering, top-off)

1. Use a MOSFET driver board (one channel per pump) rated for at least 2 A per channel, with flyback protection. Do not drive a pump directly from an ESP32 pin.
2. Board signal inputs go to the node's outputs; board GND goes to node GND.
3. A separate 12 V supply feeds the board's power terminals; each pump connects to one output channel. The 12 V supply's minus and the node's GND must be joined (most boards do this through their GND terminal).
4. **Watering tank:** mount the low float so it opens when the tank is nearly empty, and wire it to Input 2 and GND on the tent2 node. Pumps refuse to run when it reads low, and also when it is unplugged.
5. **Stop siphoning:** each pot's tube must end above the water level of the tank, or have an anti-siphon valve. Otherwise water can keep flowing after the pump stops.
6. Stand every pot in a saucer, and put the tent's leak sensor where overflow would collect.

### Check each output before trusting it

Use the Controls page, with the load plugged in:

- [ ] Each device turns on and off with **On** / **Off**, and the chip matches what the device is really doing.
- [ ] Set a device to **On**, then unplug the node's USB power. Lights, fans, heater and tower pump go **off**; the air pump and circulation pump keep **running**. Plug the node back in.
- [ ] Wet any leak sensor: every water pump on every node stops within a few seconds, the air pump keeps running, and the pumps stay stopped after you dry the sensor until you press **Clear the alarm**.
- [ ] Lift the reservoir's low float out of the water: the heater and circulation pump stop.
- [ ] **Water now** on one pot: the pump runs for about 8 seconds and stops by itself. Press it again straight away: it is refused.
- [ ] Measure what one dose delivers (catch it in a cup) and adjust `dose_s` in `config/config.yaml` so a dose suits the pot size.
- [ ] Unplug the Pi for 5 minutes: lights follow their schedule, the heater keeps regulating, and the System page shows the nodes went into fallback when the Pi is back.
- [ ] Leave auto-watering **Off** for a pot until its sensor is calibrated and you have watched its readings for a few days.

## 9. Phase 3: pH and EC probes

Diagram: [water node, pH and EC](wiring/water-chemistry.svg).

**What to buy (cheap is fine):** an analog pH kit (a BNC probe plus a small amplifier board
with an analog output pin, often marked `Po`), and an analog "TDS meter" board with its
two-pin probe. For calibration: pH 4.0 and 6.86 or 7.0 buffer (powder sachets are cheapest)
and a bottle of 1413 µS/cm EC solution.

1. **pH board power.** If the board is rated for 3.3 V, wire `V+` to 3V3. If it is 5 V-only
   (the common PH-4502C is), power it from the node's 5 V pin and put a **voltage divider** on
   its output so the ESP32 never sees more than 3.3 V: a 10 kΩ resistor from `Po` to the
   analog terminal, and a 20 kΩ resistor from the analog terminal to GND. The calibration
   absorbs the divider, so the readings stay correct.
2. **pH output** `Po` (or the divider's midpoint) goes to Analog 1.
3. **EC board:** `A` to Analog 2, `GND` to GND, and `VCC` to **Output 5**, not to 3V3. The
   node switches the board on for a couple of seconds per reading so it cannot disturb the pH
   probe.
4. Keep the boards in the enclosure and the probe cables away from mains cables. Hang the
   probes in the control bucket at least a hand's width apart, tips submerged, caps off.
5. **Calibrate** on the System page, in this order:
   - **pH:** rinse the probe, stand it in the 7.0 (or 6.86) buffer, choose that buffer and
     press **Capture**. The hub waits until the reading is steady, which can take a minute.
     Rinse, then repeat in the 4.0 buffer. A third buffer (9.18 or 10) is optional.
   - **EC:** stand the probe in the 1413 solution, type `1413`, press **Capture**.
   - If the page says the points do not fall on a line, the probe is dirty or worn out.
6. Check against a handheld meter if you have one. Expect about ±0.2 pH and ±10 % EC.
7. The System page shows how old each calibration is, and an alert reminds you when pH (30
   days) or EC (90 days) is due.

Troubleshooting:

| Symptom | Likely cause |
|---|---|
| pH reading wanders or jumps when the EC reading updates | EC board wired to 3V3 instead of Output 5 |
| pH never settles during capture | Air bubble on the bulb, a dry or old probe, or a loose BNC connector |
| pH volts barely change between buffers | Probe dead or still capped; on a PH-4502C, the offset trimmer turned to an extreme |
| EC shows `—` | The reservoir temperature probe is not reporting (EC needs it), or EC is not calibrated |
| EC stuck near its maximum | Solution stronger than the cheap board can measure (about 2 mS/cm) |

## 10. Phase 4: dosing pumps

Diagram: [dosing node](wiring/dosing-node.svg).

**Read this first.** These pumps put concentrated acid, base and fertiliser into the water
your plants live in. A wrong dose can kill everything in the reservoir overnight. Build it,
test it with plain water, and run it in **Suggest** mode for a couple of weeks before you
consider **Automatic**.

**Parts:** four 12 V peristaltic pumps, a 4-channel MOSFET board, a 12 V supply (3 A),
silicone tubing, four labelled bottles, a leak sensor module, a tray big enough to hold the
bottles and pumps, and a small measuring cylinder or syringe.

1. **Wire the node** as in the diagram: the MOSFET board's four inputs to Outputs 1–4, its
   GND to the node's GND, the 12 V supply and the pumps on its power terminals. The leak
   sensor goes on Input 1, with its plate in the tray.
2. **Label everything**: each pump, each tube at both ends, each bottle. pH down, pH up,
   Nutrient A, Nutrient B. A swapped tube doses the wrong chemical.
3. **Stand the bottles and pumps in the tray**, below the level of the reservoir's rim, so
   nothing can siphon in. Wear gloves and eye protection when handling pH adjusters.
4. **Test with plain water first.** Fill all four bottles with water and do every step below
   before any chemical goes in.
5. **Prime and measure each pump** (Water page → *Pumps and flow calibration*). Put the
   pump's outlet in the measuring cylinder, **not the reservoir**. Press **Prime 5 s** until
   water reaches the end of the tube, empty the cylinder, press **Run 30 s**, then enter how
   many mL came out and press **Save**. Repeat for all four.
6. **Check a dose is what it says.** With the outlet still in the cylinder, press
   **Dose pH down (1 mL)** and measure. Do the same for the others (wait for the mixing
   timer between doses, or check them on different days).
7. **Check the cutoffs** with water in the bottles:
   - [ ] Wet the leak sensor in the tray: a dose is refused, on the page and at the pump.
   - [ ] Turn the circulation pump off on the Controls page: a dose is refused.
   - [ ] Unplug the Pi: no pump runs, whatever was requested before.
8. **Move the outlet tubes into the reservoir**, near the circulation return so doses mix
   quickly, held above the waterline so they cannot siphon. Swap the water for chemicals:
   dilute pH adjusters as their labels say, and never mix concentrates together.
9. **Start in Suggest mode.** The hub proposes one small dose at a time; you approve it and
   watch what it does on the pH and EC charts. Adjust `ph_dose_ml`, `nutrient_dose_ml` and
   the targets in `config/config.yaml` until one dose moves the reading a small, predictable
   amount. A bigger reservoir needs a bigger dose; the limits cap it at 2 mL.
10. **Automatic mode** is a deliberate choice: the page asks you to confirm. Recalibrate the
    probes first, and keep checking against a handheld meter every week or so.

If dosing stops by itself, the Water page says why. Fix the cause (empty bottle, air in a
tube, a probe that has come out of the water, a calibration that is overdue) before pressing
**Re-enable dosing**.
