# What the house expects

*The names the packages read, the jobs a light can have, and what each part of the house needs.
Level 1, it's a reference.*

The first question anyone asks is whether their stuff will work with this, and the honest answer
is that the packages don't care what brand anything is, they care what it's called. Every package
in `ha/config/packages/` reads a fixed set of entity names, `person.resident`, `vacuum.robot_vacuum`,
`binary_sensor.front_door` and so on, and `tools/setup_ha.py` renames your devices onto those names
from `house.toml`. So a Roborock and some other vacuum are the same thing to the house, as long as
the other one ends up as `vacuum.robot_vacuum` with the same kind of entities around it. I've only
run it with the devices I own, which the "tested with" column says, so anything else is a good guess
rather than a promise.

## One resident

The whole house is built around one person living alone, with guests now and then. Presence is one
phone, the wake-up wakes one person, the asleep filter models one sleeper, and the welcome home is
for whoever `person.resident` is. Guest mode covers having people over. Two people with two phones
is the first thing that would need real changes (presence by "anyone home", and a wake-up per
person), and I haven't built it because I haven't needed it. I'd start in `presence.yaml` and
the asleep filter in `custom_components/house_control` if I did.

## Always there

These come with the Hub and Home Assistant itself, nothing to set up:

| Entity | From |
|---|---|
| `binary_sensor.hub_500_motion`, `light.hub_500_screen`, `sensor.hub_500_*` | the Hub's own services (`host/50-screen.sh`, `host/55-stats.sh`) |
| `assist_satellite.hub_500_voice_assist_satellite`, `media_player.hub_500_voice_media_player`, `switch.hub_500_voice_mute` | the voice satellite (`host/70-voice.sh`), once Home Assistant adds it |
| `tts.kokoro`, `stt.parakeet` | the speech engines on the Hub (`host/74-kokoro.sh`, `host/76-parakeet.sh`) |
| `weather.forecast_home`, `sun.sun` | Home Assistant's defaults |

## You and the phone

| Entity | How it gets there |
|---|---|
| `person.resident` | your person in Home Assistant, named in `resident.person`, renamed by the deploy |
| `device_tracker.phone`, `sensor.phone_ssid`, `sensor.phone_battery_state`, `binary_sensor.phone_focus` | the companion app, with the phone called `Phone` in it |
| `notify.mobile_app_phone` | the same name. The app's own can't be renamed after the phone signs in, so name the phone first, or put the one it got in `devices.phone_notify` and the deploy adds this name on top |
| `sensor.home_resident_distance`, `sensor.home_resident_direction_of_travel` | the Proximity integration, which the deploy adds |
| `input_text.home_wifi` | `resident.home_wifi`, your network's name |
| `sensor.phone_geocoded_location` | the companion app's geocoded location sensor, if you turn it on: its areas of interest name a market or a park for the journal ([journal.md](journal.md)) |
| `zone.work` | a zone you make called Work, big enough for the whole site, so the journal asks about work once a day |

Tested with an iPhone. Android's app has the same sensors under the same names, and the packages
compare the battery state without caring about case, since iOS says "Charging" and Android says
"charging". The Shortcuts that make leaving and arriving quick are iOS automations; on Android,
Tasker or the app's own sensors can run the same scripts ([sensing.md](sensing.md)).

## Lights

Every light gets a layer and, if it needs one, a job. Both are labels the deploy sets from the
`[[light]]` tables, and the looks find lights by label, so there's no list of lights to keep in
step anywhere ([lighting.md](lighting.md) has why it's done by layer).

| Label | What it means |
|---|---|
| `light_ambient` | a lamp: the soft light the room lives in. On whenever someone's home and awake, following the light curve |
| `light_task` | an overhead or a work light. On only when someone asks or switches it on; a look only dims it or turns it off |
| `light_accent` | decoration, a printer's case light. On through the evening, never off mid-print |
| `light_sunrise` | the light the wake-up fades up. One or more, usually the bedroom overhead |
| `light_bedside` | the bedside lamp: on with the alarm, left on at Night if it's on (reading in bed) |
| `light_no_dim` | a dimmer switch on bulbs that can't dim: only ever full or off |
| `light_no_fade` | a lamp whose firmware can't fade: everything goes straight there, the blend's steps included |
| `light_stand_in` | takes over its room's ambient light, low, when every lamp in the room is dead |
| `light_keep` | left alone by every look but Night, Away and lights out (a bathroom light on the fan's switch) |

A plug with a lamp on it is fine: give its switch as the `entity`, and the deploy wraps it as a
light with Switch as X.

## Doors

| Entity | What uses it |
|---|---|
| `binary_sensor.front_door` | someone home without the phone (the "wasp in a box", [control.md](control.md)), leaving, arriving |
| `binary_sensor.bedroom_door`, `binary_sensor.bathroom_door` | the vacuum skips a room behind a shut door, the asleep filter, the bathroom being occupied |

Any other door sensor labelled `room_door` counts for the vacuum too, by the room it's in. Tested
with Aqara door sensors through the G410's Zigbee hub, bridged over Matter. Without a front door
sensor, home is simply the phone being home, which is how most houses run anyway.

## The rest, each optional

Each of these is a package that sits there doing nothing until its entities exist. Leave the line
in `house.toml` empty and nothing is lost but that part.

| Part | The names it reads | Tested with | In `house.toml` |
|---|---|---|---|
| TV | `media_player.fire_tv` underneath, `media_player.tv` on top, `sensor.tv_status` | a TV with Fire TV built in, over ADB | `[fire_tv]` |
| Vacuum | `vacuum.robot_vacuum`, `sensor.robot_vacuum_*` | a Roborock | `devices.vacuum` |
| Doorbell | `event.doorbell_ring`, `camera.doorbell`, `binary_sensor.doorbell_motion`, `sensor.doorbell_battery`, `binary_sensor.face_*` | an Aqara G410 over HomeKit Controller | `devices.doorbell`, `resident.face` |
| Computer | `sensor.computer_session_state`, `sensor.computer_last_active`, `sensor.computer_monitor_power_state`, `button.computer_lock`, `media_player.computer`, `notify.computer`, and `sensor.desk_power` from a measuring plug | a Windows laptop with HASS.Agent | `devices.computer`, `devices.desk_power` |
| Printers | `sensor.klipper_*`, `number.klipper_*_target`; `sensor.bambu_*`, `light.bambu_chamber_light` | Moonraker, ha-bambulab | `devices.klipper`, `devices.bambu`, `[klipper]` |
| Washer | `sensor.washer_current_status`, `sensor.washer_remaining_time`, `event.washer_notification`, `event.washer_error` | LG ThinQ | `devices.washer` |
| Work calendar | `calendar.work` | a free/busy iCal address | `[calendar]` |
| Sleep tracker | `sensor.oura_ring_*` | an Oura ring, through the community integration | `extras.install` |
| Cloud agent | `conversation.jarvis_cloud` | any provider whose conversation agent has a prompt field | `voice.cloud_agent` |

The TV has two more optional pieces in `tv/`: a debloat that switches off Amazon's ads, content
recognition and telemetry, and a small keeper app that stops a Fire OS update from switching ADB
debugging off and cutting the house off from the TV ([tv/README.md](../tv/README.md)).

`[devices]` renames by prefix: give any one entity of the device, and every entity on that device
that shares its name moves over. `vacuum.roborock_s8` becomes `vacuum.robot_vacuum`, and
`sensor.roborock_s8_battery` becomes `sensor.robot_vacuum_battery`. It only renames when the new
name is free, and it says what it did.

## When something's missing

Nothing errors because a part isn't there. Every template reads a missing entity as unknown and
moves on, every action on an optional device checks the device exists first, and the dashboard
only gets the pages your house has. The two things that do have to be right are the phone's notify
service (`notify.mobile_app_phone` is how anything reaches you away from the Hub) and
`person.resident`, and the deploy says so when either is missing.

What Jarvis calls things is yours too, without touching a package: `[names]` in `house.toml` is what
he says for the printers, the vacuum and the computer, and listens for, `voice.address` is how he
addresses you, and the deploy writes both into the packages ([`tools/build.py`](../tools/build.py)).
A house that has always called its printer the Voron keeps hearing "the Voron's finished".

Adding something this doesn't cover is the same as adding it to any Home Assistant: a package of
your own in `ha/config/packages/` in your house folder gets laid over this repo's and deployed with
the rest. Pick names that won't collide with
these, and if it switches lights, go through `script.light_set` so the arbiter knows about it.
That one rule is most of what keeps the house from fighting itself.
