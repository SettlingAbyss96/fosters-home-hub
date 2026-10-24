# What the house can actually see

*Level 2 to 3. Every signal the house has, what it really says, how late, and how far to trust it.
The estimates built on top of them are in [control.md](control.md).*

The house has very few sensors in the usual sense: one PIR in the Hub, wherever the Hub is, a few
door sensors and a doorbell if there are any. Everything else it knows, it works out. From the
controls side that's state estimation: you can't put a sensor on the thing you care about ("is
he asleep", "is someone in"), so you watch what you can measure and reason backwards. The trick is knowing what each
signal really says, how late it says it, and how much to trust it.

## The signals

Roughly from fastest to slowest:

| Signal | What it really says | How late | Trust |
|---|---|---|---|
| Phone Shortcuts (Wi-Fi joined, charger, alarm stopped, car parked) | That exact thing, the moment it happens | Instant | High, but only the ones set up on the phone |
| A light switched | Someone touched it, if no automation did (see below) | About a second (Matter) | High |
| Doorbell ring, motion, faces | Someone's at the door. Faces are a guess | A second or two | Ring: high. Motion: medium. Face: "looks like" |
| Hub motion | Someone moved in front of the Hub. Or the robot vacuum rolled past | A second, then 30 s to clear | Medium |
| Computer input and lock (HASS.Agent) | Hands on the keyboard. Unlocked plus touched in the last 90 s means a person at the desk | 15 s | High |
| Desk and lamp watts (plugs) | Something's on. Not who | Seconds | High for "on", useless for "who" |
| TV (Android Debug Bridge) | What's on, playing or paused | 5 to 10 s | High |
| Washer (LG ThinQ) | Running, done, what went wrong | Seconds to a minute, cloud | High |
| Printers | Everything, in detail | Seconds | High |
| Phone app sensors (charging, Focus, SSID) | The same things Shortcuts say, eventually | Whenever the phone feels like waking the app | Low on timing |
| Phone GPS (person.resident) | Roughly where the phone is | Minutes, and it wanders | Medium. Never alone |
| Oura ring | How the night actually went | Hours. Only after it syncs | The best truth there is, after the fact |

![Range bars of how late each signal arrives, on a log scale from 0.1 s to 6 hours: Shortcuts, light switches, door sensors and the PIR within a second or two; the TV, the computer and the washer in seconds to a minute; the phone's GPS and app sensors in minutes; the Oura ring in hours](figures/sensing-latency.svg)

*Five orders of magnitude. Anything that triggers has to come from the left half.*

The Oura one surprised me. I'd assumed the ring could tell the house "asleep" live. It can't: it
syncs when its app wakes up, and its newest heart rate is usually hours old. So it can't be a
trigger. What it can be is the answer key. More on that below.

## Who switched that light

This is the most useful thing in the whole system and nobody talks about it. Every state change in
Home Assistant carries a context. An automation or a script switching a light leaves its own
fingerprint on it (a parent id). The dashboard or the app leaves a user id. A light switched at the
wall, reported over Matter, has neither. So "the kitchen light came on" splits into three very
different facts:

- an automation did it: means nothing about people
- the dashboard did it: someone with my login, possibly not home
- the wall switch did it: **a person is standing in that room right now**

Without this, "no sign of life for 40 minutes" fails the moment the house dims its own lights,
because the dimming looks like someone moving. With it, the house only counts what people did.

Except it has a hole, which the test bench found: an automation started by the clock (which is how
the alarm starts) leaves no parent on what it changes either, and a light reporting back late from a
fade carries no context at all. So the real test is memory: every light command is written down
before it's sent, and a change that doesn't match a recent one is a person. The exact rule, with its
tolerances, is in [control.md](control.md#what-counts-as-by-hand). The context only says which
person: the dashboard and Jarvis carry a user, the wall doesn't.

## Combining signals

Put two or three signals together and some conclusions stop being guesses:

| When | Then | Used in |
|---|---|---|
| Away, and the phone joins the Wi-Fi (or the car parks) | Here, not in. Probably parking | Arrival waits for the door |
| ...and the doorbell sees movement, or your face | At the door. It opens in about seven seconds | Arrival lights |
| ...and the Hub sees someone | Inside | Arrival, greeting |
| Away, no guests, a wall switch flips | Someone's inside who isn't you | `security.yaml` |
| Away, no guests, the computer unlocked and used | Same, and they're at the desk | `security.yaml` |
| Away, and the desk is still drawing power 30 min later | It got left on | Phone offers lock or sleep |
| Late, lights on, and nothing at all for 40 minutes | Asleep, or reading very still | Dims first, then goodnight |
| Unlocked computer touched in the last 90 s | Out of bed | Stops the alarm |
| The washer said done 45 minutes ago and still says done | The laundry's still in it | One reminder, then another |
| A face match while you're out | Probably that person. Probably | Notification, hedged |

Notice what's missing: nothing ever flips the house into or out of Away on one weak signal. GPS
wanders, faces get mixed up, the PIR sees the vacuum. The strong conclusions all need two things
that can't both be wrong the same way.

That last part is the whole design rule, and it's easy to get wrong. If two signals fail
independently, needing both multiplies their error rates:

```math
P(\text{both wrong}) = P(\text{A wrong})\,P(\text{B wrong} \mid \text{A wrong})
```

and the second factor is only $`P(\text{B wrong})`$ when they really are independent. The phone's
GPS and the phone joining the Wi-Fi look like two signals, but they're one phone: the day it spends
an afternoon somewhere without you, both are wrong together, and the conditional term is 1.
The front door doesn't care where the phone is, which is why it's the signal that fixed it.

## Asleep

The fuzzy one. It started as a naive Bayes sensor, the textbook tool for lots of weak evidence where
none of it is decisive: late, home, a quiet house, nothing touched, the phone on the charger, Focus
on, not at the computer, the TV off, the house in Night. Its first night it was about right. It
still had two classic problems: it counted the late hour and the house in Night as separate
evidence when they're mostly the same thing, and it had no memory, so it never noticed anyone get
up in the night. A Bayes filter replaced it, where the context changes how
likely falling asleep is instead of piling up as evidence ([control.md](control.md#estimating-asleep)).

With an Oura ring, the ring is the answer key: every morning its real bedtime gets compared with when the
house first said asleep, and the gap goes in `sensor.asleep_guess_error`. A few weeks of that and the
filter's numbers stop being guesses.

One way to spoil that, which bit me early: "at the desk" counts as typing, and typing tells the
filter you're awake a thousand to one. It was on whenever the desk plug read over 35 W with the
computer's agent not answering, and four days of the plug say a locked laptop charging sits at 35
to 40 W, while the agent drops out for hours. So it flipped 12,000 to 14,000 times a day, and every
flip pulled the belief back to zero. That night the house didn't call me asleep until nearly four
in the morning, so the fell-asleep check never got its turn, and the lights burned until I left.
In use that desk draws 55 to 95 W, so the line's at 50 W now (`input_number.desk_in_use_watts`, set
yours a little over what your desk draws locked), with 5 W of hysteresis so a desk sitting on it
can't chatter. Replayed without the false typing, the same night says asleep a couple of hours
earlier, and the filter's still a little slow with the lights on, which is what the ring's nights
are for.

The desk itself gets better from the bedroom radar node. Power is a guess at a person from whatever's
plugged in, and the radar can see someone sitting there, so `bedroom-sense` has a desk band ("Desk
from" and "Desk to", set once on the wall by sitting at the desk and reading the distance). Once
it's up, "At the desk" is the radar saying so or the computer just touched, and the plug's power
drops out of it ([esp32.md](esp32.md)).

## Reading the phone through Shortcuts

The app's own sensors are fine for "where's the phone, roughly" and terrible for "right now". iOS
decides when the app gets to wake up. Shortcuts personal automations don't have that problem, and
Apple lets the Alarm, Sleep and Time of Day triggers and the setting triggers (charger, Focus,
Wi-Fi, Bluetooth) run without asking. Each one made on the phone runs one script here
(`packages/inference.yaml`), and on Android, Tasker can run the same ones:

| On the phone | Runs | What the house does with it |
|---|---|---|
| Wi-Fi: joins your network | Phone joined the home Wi-Fi | Arrival |
| Charger: connected / disconnected | Phone went on / came off the charger | A fact for "probably asleep", a sign of life |
| Alarm: any, is stopped / is snoozed | Phone alarm stopped / snoozed | A sign of life (not "up", people stop alarms in their sleep) |
| Sleep: bedtime begins / waking up | Phone says bedtime / waking up | Logged, for the asleep sensor to learn from |
| Wi-Fi: leaves your network | Phone left the home Wi-Fi | Leaving, the moment the door's check says nobody's in |
| CarPlay or the car's Bluetooth: disconnects / connects | Car parked / car started | Parking counts like the Wi-Fi on the way in, starting is leaving |

## What it can't see yet

- The bedroom. Nothing in there knows if anyone's in bed. A mmWave presence sensor sees someone
  breathing, not just moving, which is the whole difference for "asleep" and for the alarm's
  "still in bed?". With a bed zone it's the best "up" signal there could be, much better than
  waiting for someone to walk past the Hub. That's `bedroom-sense` in [esp32.md](esp32.md)
- Showers. The wake-up assumes a bathroom light on means a shower. A humidity sensor in there
  would know: humidity climbing a few percent a minute is a shower, nothing else does that
- Which room anyone's in, generally. The Hub's PIR is the only motion sensor and it sits wherever the
  Hub is
- Light. The light curve works the daylight out from the sun's height and the cloud forecast, and
  guesses what 35% of a lamp does at your eyes. A lux sensor in the window and one at eye level
  would measure both
- Power for printers, without a measuring plug under each

## The doors

Door sensors through a Zigbee bridge (on mine, Aqara's, through the G410 doorbell's chime) each
answer in under a second. The front door is the truth for leaving and arriving: the wasp
in a box ([control.md](control.md#estimating-someone-home-the-wasp-in-a-box)) knows someone's home
without a phone, and the arrival lights wait for the door instead of guessing seven seconds after
the doorbell sees movement. The inside doors mostly say what can't be true: the vacuum can't clean
behind a shut door, and the bathroom with its door shut and the light on isn't empty.

## Sensors worth buying

I don't want a drawer of sensors that each tell the house something it never uses, so the rule is
one sensor per decision it changes. The interesting part is less the sensor than the path it takes
into Home Assistant, because that's where things break.

The G410's chime is already an Aqara Zigbee hub and a Matter bridge, and the bridge is proven here:
it's how the faces arrive. Aqara even sells the G410 in a kit with three of its door sensors, so the
Zigbee ones pair to it without drama, and the bridge passes them on as plain Matter contact,
temperature and humidity sensors. Nothing new to set up on this side. The catch is that everything
then hangs on Aqara's app and that one chime, and people on other platforms do report the odd bridged
sensor dropping off until it's re-paired. For three or four sensors I can live with that.

What I'd skip: the Thread versions (the door sensor P2, the W100 climate sensor). Home Assistant
here has no Thread network of its own (no border router it holds the keys to), so they'd go through
the Aqara app anyway, with more setup and the P2's reputation for falling off after outages. And a
Zigbee stick for Home Assistant itself (Home Assistant's ZBT-2 or a Sonoff dongle, passed through to
the VM) is the better answer the day there are ten sensors or one that isn't Aqara's, not before.

So, in order of what each one changes:

| What | Through | What it changes |
|---|---|---|
| Aqara Door and Window Sensor (Zigbee), front and inside doors | G410, Matter bridge | Arrival on the real door, leaving vs arriving, someone's-in, rooms the vacuum can reach |
| A radar node in the bedroom (`bedroom-sense`), built rather than bought | Wi-Fi, ESPHome (local) | Out of bed ends the alarm, in bed for real starts the asleep logic. Needs USB power by the bed |
| A radar and humidity node in the bathroom (`bathroom-sense`), or the Aqara Temperature and Humidity Sensor (Zigbee) if there's no power by the mirror | Wi-Fi, ESPHome, or the G410 | Shower detection for the morning, the fan, and the house not mistaking a shower for nobody up |
| Aqara Water Leak Sensor (Zigbee), under the washer | G410, Matter bridge | Cheap insurance. Not a decision, just a disaster caught early |

The bedroom row used to be an Aqara FP2. It would do the job, but the kits people rate (Apollo's,
the Everything Presence Lite) are an ESP32 around radar chips that cost a few dollars on their own,
so the rooms that need one get a node I build ([esp32.md](esp32.md)). The door and leak sensors
stay Aqara's, because for those a battery and Zigbee beat a USB cable.

Temperature sensors in every room I'd leave until there's a thermostat or the blinds to act on
them. A number on a dashboard that nothing uses is exactly the drawer I'm trying not to fill.

The other thing worth knowing, because it costs almost nothing: the phone's own Bluetooth can say
which room you're in. The Home Assistant app can broadcast an iBeacon, and every ESP32 node is a
Bluetooth proxy already, so the nodes plus the Bermuda integration turn that into "the phone's in
the bedroom". The phone isn't the person, but at 3 a.m. it usually is.

## What I'd like to build next

- Feed the Oura nights back into the bedtime plan: a week of short nights should move the nudge
  earlier on its own, the sleep debt is right there in the ring's data
- The ESP32 nodes ([esp32.md](esp32.md)): radar presence in the bedroom, the living room and the
  bathroom, light at eye level, the daylight at the window, the air. Most of what this page says the
  house can't see, for about $15 a room
- The washer's delayed start timed so a load finishes about when you usually get home
- Tuning the asleep sensor's numbers once there are a few weeks of Oura nights to check it against
