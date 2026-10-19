# ESP32 sensor nodes

*Level 2. Why the next sensors are ones I build, what each node is for, what goes in it, and how
they get from `esphome/` onto the wall.*

From the controls side, every open question the house has left is an observability problem: the
state is there, nothing measures it. Is anyone in bed, or on the couch in a room the Hub can't see?
How much daylight is actually coming through the windows, as opposed to what the sun's height and a
weather forecast suggest? Is the evening really down at 30 lux at the eye, or is that a guess at
what 35% of a lamp does? Is the bathroom light on because of a shower? One PIR in the Hub and a
phone that sleeps when it likes can't answer any of those.

The commercial answer is a $35 to $40 sensor per room. The thing is, the good ones (Apollo's MSR-2,
the Everything Presence Lite) are an ESP32 running ESPHome around the same Hi-Link radar chips you
can buy on their own for $3 to $6. Build it and a room node comes out at around $12 to $20, the case
is a print away if you have a printer, and the firmware is a YAML file in this repo instead of someone else's
release schedule. At five or six nodes that's a real difference, and more to the point it means I
can put a sensor everywhere one would answer something, instead of rationing them.

## The board

Everything is built on Seeed's XIAO ESP32-C6, about $5. Wi-Fi 6, Bluetooth 5 that's good enough to
make every node a Bluetooth proxy (the C3 struggles at that), and the Thread and Zigbee radios
sitting there for later, in a board the size of a thumbnail. Two quirks are handled in
`esphome/common/xiao-c6.yaml`: its antenna switch has to be told to use the ceramic antenna (GPIO3
and GPIO14 both low), and the generic C6 board definition assumes 8 MB of flash where the XIAO has
4. The path light builds to a third of its RAM and half its flash. A room node is fuller, 42% of
the RAM and 83% of the space a firmware gets, and nearly all of that is the Bluetooth proxy, so
that's the first thing to drop if a room node ever needs more.

## The nodes

| Node | Parts | Roughly | Answers |
|---|---|---|---|
| `window-light` | XIAO C6, VEML7700 | $8 | how much daylight the windows let in |
| `living-sense` | XIAO C6, LD2410C radar, SHT40, VEML7700 at eye level | $18 | someone on the couch, the evening light at the eye |
| `bedroom-sense` | the same | $18 | in bed or not, the light and air where you sleep |
| `bathroom-sense` | XIAO C6, LD2410C, SHT40 | $14 | someone in there, a shower by the humidity |
| `path-light` | XIAO C6, AM312 PIR, half a metre of WS2812B | $10 | a dim amber floor light from bed to bathroom at night |

The prices are rough, from listings when I wrote this, and they move. The radar is the LD2410C
because it sees people sitting still, which is the whole point, and Apollo's kit uses the same family.
The LD2450 tracks positions (couch versus desk) but is weaker at still bodies, so it's a later
experiment, not the default. The light sensor is a VEML7700 rather than the usual BH1750 because the
BH1750 tops out at 65,535 lux and a sunny window will pin it; the VEML7700 reads to about 120,000.

Each config is a few lines, because the parts live in `esphome/common/`: `base.yaml` (Wi-Fi, the
encrypted API, updates over Wi-Fi, the time), `xiao-c6.yaml` (the board), `room.yaml` (radar,
SHT40, Bluetooth proxy) and `eye-light.yaml` (the VEML7700).

### Wiring

Same on every XIAO: I2C on D4 (SDA, GPIO22) and D5 (SCL, GPIO23) for the VEML7700 and the SHT40,
which share the bus at different addresses (0x10 and 0x44). The radar's UART on D6 (GPIO16) to its
RX and D7 (GPIO17) to its TX, with 5 V from the XIAO's 5V pin. The path light's strip data on D2
(GPIO2) through a 330 ohm resistor, its PIR on D1 (GPIO1).

### The path light decides for itself

The path light is the one node that acts on its own, on the chip. It asks Home Assistant whether the
house is in Night, falls back to the clock (10 PM to 7 AM) if it can't, and on movement it puts the
strip on at 4% amber, off again a minute and a half after the movement stops. A night light that
needs Home Assistant up to work is a night light that fails on the night of a power cut, which is
exactly when you need one.

## Building and flashing

ESPHome lives on the Hub (`host/78-esphome.sh`), pinned to 2026.9.1, and the Hub does the compiling,
so nothing gets installed on your computer. The secrets stay on the Hub in
`/opt/ha-hub/esphome/secrets.yaml`: the script makes the API key and the update password the first
time and copies in the Hub's timezone (it says roughly where the house is, so it isn't in the repo
either), and the Wi-Fi name and password are yours to put in.

```bash
tools/esphome.sh config            # check every node's YAML, builds nothing
tools/esphome.sh bin path-light    # build it, copy the image to esphome/build/
tools/esphome.sh run path-light    # after the first flash: build and update over Wi-Fi
tools/esphome.sh logs path-light   # its log, live
```

The first flash is over USB from your computer: `bin` drops `esphome/build/<node>.factory.bin`, the XIAO
goes in by USB-C, and [web.esphome.io](https://web.esphome.io) in Chrome or Edge installs it. Then
Home Assistant finds the node on its own and asks for the API key, which is the `api_key` line in
the secrets file. Every update after that is `run`, over Wi-Fi.

## What each one changes in the house

- `window-light` replaces the worked-out daylight in the light curve with a measured one
  ([lighting.md](lighting.md)), which makes a floor lamp the first real closed loop in the house
- The eye-level sensors close the other loop: the wind-down aims for about 30 lux at the eye, and
  with a reading the lamp can be trimmed to hit it instead of sitting at a fixed 35%
- `bedroom-sense` gives the asleep filter its best evidence yet, still in bed versus up, and lets
  the alarm end when you're out of bed instead of when the Hub sees you
- `bathroom-sense` turns "the bathroom light is on" into "someone's showering", and keeps the light
  on for someone standing still at the mirror
- Every node is a Bluetooth proxy, so the phone and the ring can be placed room by room later

## What I'd like to build next

- Printed enclosures for each node, with the light sensors behind a clear window and the SHT40 out
  of the board's own heat (an ESP32 runs a couple of degrees warm, and it shows in the reading)
- An LD2450 on the couch side of the living room, to see whether "on the couch" as a zone is worth
  the extra
- CO2 in the bedroom (an SCD41 is the usual one), if the nights say the air's worth watching
- A node with a small speaker in the bedroom, so the alarm doesn't depend on Home Assistant either

## References

- [ESPHome LD2410](https://esphome.io/components/sensor/ld2410/), [VEML7700](https://esphome.io/components/sensor/veml7700/) and [SHT4x](https://esphome.io/components/sensor/sht4x/) components
- [Seeed, getting started with the XIAO ESP32-C6](https://wiki.seeedstudio.com/xiao_esp32c6_getting_started): the pins and the antenna switch
- [Derek Seaman, ESP32-C3 vs C6 vs S3 for ESPHome (2026)](https://www.derekseaman.com/2026/01/seeed-studio-esp32-showdown-c3-vs-c6-vs-s3-esphome-edition.html): why the C6 for Bluetooth proxies
- [atomic14, which presence sensor](https://www.atomic14.com/esp32/sensors/presence-sensors/): the radar modules compared, and their prices
- [Apollo's mmWave sensor comparison](https://wiki.apolloautomation.com/products/general/mmwave-presence-sensor-comparison/): the kits side by side
- [Everything Presence Lite on the ESPHome device database](https://devices.esphome.io/devices/everything-presence-lite)
- [atomic14 on the VEML7700](https://www.atomic14.com/esp32/sensors/veml7700/) and [the BH1750](https://www.atomic14.com/esp32/sensors/bh1750/): why not the BH1750 in a window
