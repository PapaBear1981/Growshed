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
| `tent1`, `tent2` | Outside each 4×4 tent | Air temperature, humidity, light, floor leak | [tent node](wiring/tent-node.svg) |
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
| SHT45 temperature/humidity board | 1 | 1 | 1 | |
| BH1750 light sensor board | 1 | 1 | — | |
| DS3231 clock module + CR2032 battery | 1 | 1 | — | |
| Leak sensor module (see below) | 1 | 1 | 2 | |
| DS18B20 waterproof probe | — | 1 | 1 | The stainless-steel kind on a cable |
| 4.7 kΩ resistor | — | 1 | 1 | |
| Vertical float switch | — | 1 | 2 | |
| Printed enclosure | 1 | 1 | 1 | [`hardware/enclosure/`](../hardware/enclosure/README.md) |

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
   | `0x44` | SHT45 |
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

**If a float reads backwards:** most float switches can be reversed. Pull off the retaining
clip, turn the float upside down, and put it back.

**Leak module adjustment:** turn the blue knob until the board's second LED is off when the
plate is dry and comes on with a single drop of your actual water on the plate.

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

## 8. What changes in Phase 2

Each node gains signal wires to the relay outlet boxes (lights, fans, heater, pumps), using
the spare cable slots, and the water and dosing nodes gain a 12 V supply for small pumps. The
sensor wiring above stays exactly as it is.
