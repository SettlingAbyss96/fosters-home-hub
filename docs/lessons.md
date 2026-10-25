# What broke along the way

*Level 1 to 2. Every problem that cost me more than an hour, grouped by where it lived, with what
it turned out to be. Mostly so nobody solves the same thing twice, me included.*

Most of these are a few watts or a few hundred milliseconds in the wrong place, and the fix is
already in the scripts and packages here. They're written down because each one looked like
something else first.

## The box

- No hardware echo cancelling. The Hub was sold as a conference speakerphone, and there's none on
  the USB stream. PipeWire's WebRTC canceller does it in software, and does it well, taking the
  speaker's own noise from -45.7 dBFS on the raw mics down to -93.3 on `hub_mic` ([voice.md](voice.md))
- The mics are quiet, only 15 to 20 dB of speech over the floor at 3 to 4 m with the hardware gain
  maxed, which is why Parakeet needs its input normalised
- The speaker DSP ignores USB volume requests, so volume is software only and the satellite's player
  does it. Out of the box everything sits at 100%, which is a lot of speaker for a kitchen
- The presence sensor is slow to start and can hang: 10 s to turn on, 21 s to the first read, and a
  stuck read gets its USB device reset. It's a PIR, so someone reading the screen without moving is
  invisible to it, which is why a touch counts as activity too
- "Off" is DDC standby, not a hard power off. The panel wakes in about 0.6 s, which is what you want
  anyway
- The touch keyboard needed a different compositor. cage has no layer-shell or input-method support,
  so an on-screen keyboard has nowhere to draw. labwc has both, but draws a fullscreen window over the
  keyboard's layer, so Chromium runs maximised in app mode instead of `--kiosk`, which turned out
  better anyway, since the page shrinks above the keyboard instead of hiding under it
- The kiosk can freeze. labwc stops presenting frames while everything still looks alive
  (`Atomic commit failed: Device or resource busy` on DP-1), most reliably a few minutes after
  opening a constantly redrawing history chart. Chromium draws in software (`--disable-gpu`), labwc
  skips direct scanout (`WLR_SCENE_DISABLE_DIRECT_SCANOUT=1`), and a watchdog takes a tiny
  screenshot every minute and restarts the kiosk after two failures, because a frozen one can still
  answer simple questions
- 8 GB is tight. The VM takes 3.8 GiB on the host (only 1.3 of it Home Assistant actually working),
  Parakeet 830 MB, and Kokoro its share, which leaves little to spare. 16 GB fixes it

## The network

- Wi-Fi can't be bridged. A Wi-Fi client can't carry a second MAC address, so the VM would end up
  behind NAT and Home Assistant's discovery breaks in quiet, annoying ways. Ethernet isn't optional
- A power cut can move things. A TV that came back on a new address left Home Assistant's Android TV
  integration retrying the old one, since it knows a TV only by IP and has no reconfigure, and avahi,
  booting mid-shuffle, saw a conflict for `ha-hub.local` and renamed itself `ha-hub-2.local`.
  Reservations fix the first ([network.md](network.md)), `22-mdns-name.sh` restarts avahi for the
  second, and the speech engines are reached by address now, not by name

## Voice and Jarvis

- The start of a sentence went missing. Said in one breath, "Hey Jarvis, who am I" came out "where am
  I": the next word can start before the wake word fires, and Home Assistant empties its audio queue
  when a run starts. A 0.256 s pre-roll and holding the audio until Home Assistant is listening fixed
  both ([voice.md](voice.md))
- Ending the turn early got no answer. `VoiceAssistantRequest(start=False)` is Home Assistant's abort.
  The last audio message with `end=True` is the normal stop
- A deploy undid the end-of-speech setting. An older line further down a deploy script set it back
  to default a few seconds after the pipeline step set it to relaxed, and nothing noticed until the
  history showed it flipping. One setting, one place
- The welcome home was a list of chores. It read out `sensor.needs_attention` every time, so a print
  that needed maintenance and a paused vacuum got announced at the door four times in one evening.
  It's a short briefing written on the way in now, and the house's upkeep stays on the dashboard
  ([routines.md](routines.md#what-jarvis-says-when-you-get-in))
- "Not negative" turned into no bad news. The chores at the door were the problem, and a prompt that
  said good or neutral only led a down market with whatever went well and never said why it fell.
  The news is told straight now, bad days and their reasons included, and only maintenance and
  chores stay out
- The morning briefing said nothing about the night. Its overnight was a printer finishing, so
  reminders or the doorbell at 2 AM never made it in, and words written on a false wake got said
  hours later, and asking for it again got the short version. A log of the night, stale words
  written again, and a repeat in full ([routines.md](routines.md#mornings-and-bedtime))
- Only a good night got a mention. Under a sleep score of 70 the morning briefing said nothing about
  sleep at all, the same good-news-only rule in another place. Every night is in it now, compared with
  the month only past a deadband, and the markets and stories follow the same idea: said once, and
  again only when they've moved ([routines.md](routines.md#when-something-gets-said-again))
- Then the briefing was the same every evening. Asking for the day's news means two web searches
  that find the same market and the same headlines every time. The digest on the Hub keeps the
  material instead, draws a different way of telling it, and retires whatever's been heard
- The overnight log kept every restart. A day of deploys restarts Home Assistant over and over, and
  a restart that everything came back from is nothing to know. A restart only gets a line now when
  something's still offline ten minutes on, and the backup only when it failed
  ([caring.md](caring.md#owning-it-isnt-caring-about-it))
- Proximity scored a daily driver like a hobby. The car's name weighed as much as the printer's, so
  everyday news about a car you only drive outscored a sport you love, which has no proximity at
  all. Using something and caring about it are separate terms in the model now
  ([caring.md](caring.md#owning-it-isnt-caring-about-it))
- Not answering Jarvis is an error. `assist_satellite.ask_question` raises when nobody says anything,
  so the house's error alert would send "something broke" every evening nobody felt like talking.
  The alert lets "No answer from" go ([journal.md](journal.md#what-gets-asked))
- Jarvis wouldn't leave a conversation alone. With guests over, two false wakes turned into a running
  commentary: an answer ending in a question opened the long follow-up window, which heard more side
  talk, and so on until it got muted. openWakeWord went back to its default 0.5, and Jarvis answers
  speech that isn't for it with "(no reply)", which the satellite turns into silence and no window
- Jarvis got stuck mid-answer. Stock Linux Voice Assistant only counts an answer as played when the
  audio ends cleanly, so a stream that broke off left it "responding" with the ring white until a
  restart. `lva-player.patch` counts an error as the end too, and a watchdog stops any answer still
  playing well past its length (0.6 s a word plus 15 s, at least 30 s)
- The TV talks over you. Echo cancelling only removes the Hub's own speaker. TV dialogue held one turn
  open for 14 s, and YouTube's "Thanks for watching!" got answered. The TV mutes outright while the
  satellite listens, and a stray "thanks for watching" in a follow-up window closes it silently
- Changing the prompt mid-conversation broke the conversation. A cloud model's reasoning from earlier
  turns can be tied to the exact system prompt it was made under, so after a change every request in
  that conversation failed. Home Assistant can't drop one conversation, so the deploy fingerprints
  everything the prompt is built from and restarts Home Assistant when it changes
- A provider key made at the wrong level can fail with Home Assistant only saying "unexpected
  error", because the integration throws the provider's message away. A key made inside a project or
  workspace worked, and that's the natural place for a spend limit anyway
- The fast, cheap model read out headlines. With web search on, a smaller model glued search-result
  titles onto its answers, whatever the prompt said. A bigger one from the same provider gave clean
  sentences on the same questions, and was faster with search, for about three times the price, which
  at voice volumes is pocket change
- Home Assistant's own volume sentences went for the wrong speaker. "Set the TV volume to 3" set the
  Hub's speaker to 3%, because the built-in sentences dropped "TV" and used the room the request came
  from. The TV has its own sentences, one intent per direction, because the cloud agent can call a
  sentence intent as a tool but can't fill in a slot
- The cloud agent never actually opened an app. It called a generic "open app" script without saying
  which app, every run stopped at "which app?", and Jarvis still said it had. Now there's one
  parameter-free script per app, and each checks what's actually in front afterwards
- A small local model was slow and shaky with devices. A 1.7B model on Ollama managed about 8 tokens
  a second at Home Assistant's 3,000-token prompt, took 70 to 95 s on the first loose question after a
  restart, and got 4 of 5 device requests broken or backwards. It's off by default
  (`voice.local_model` brings it back), and its 2 GB is worth more to the rest of the box

## The TV

- Home Assistant can't see what a Fire TV is doing. It shows "idle" with YouTube playing. So
  `sensor.tv_status` asks the TV over ADB every 15 s, and straight after anything changes: off,
  ambient mode, the home screen, or the app in front, plus volume, mute and the title when the app
  publishes one. Playing or paused comes from Android's audio players, because YouTube's media session
  says "playing" whenever it's open, menus included
- Off is ambient mode. The remote's short power press flips between awake and the ambient pictures,
  `KEYCODE_SLEEP` is the real off, and the TV turns ambient mode off by itself after a few hours. "All
  the way off" is its own sentence
- "Select source" launches nothing on Fire OS, and the wake key can wake the Fire TV side and leave
  the panel dark. Apps start by package name over ADB, after a real power-on
- The other ways in are worse. DIAL only answers for Netflix, AirPlay and HomeKit only add power and
  inputs, there's no Google Cast or Android TV Remote protocol on Fire OS, and Alexa means a cloud
  trip for what ADB does on the LAN. Screenshots over ADB come back empty under the DRM apps, so the
  dashboard's picture hides itself there

## Lights and plugs

- A lamp wobbled 202, 203, 202, 203. Not rounding: a Govee floor lamp's firmware gets stuck mid-fade
  when one command changes colour and brightness together with a transition. The gate sends them as
  two commands ([control.md](control.md))
- A firmware update can lock a side door. A Tapo update shut out Home Assistant's no-login TP-Link
  connection overnight (a 403), while Matter carried on with on, off and dimming, and the same update
  put power and energy on the plug's Matter side, which is better anyway (instant, no polling). Matter
  is the path that keeps working
- Leaving left the alarm's lights on. The alarm holds its lights at priority 1, which leaving's
  "release everything" keeps on purpose, so leaving early on an alarm morning drove off with both on.
  Leaving lets go of the alarm's holds now, and waits for the arbiter to drop them before it goes
  Away: the release had landed 30 ms after the Away look checked
- Leaving left the lights on for 10 minutes. The door's check waited ten minutes for a sign of life,
  then the GPS had to be out for three more. Now it's five minutes on the door and the moment the phone
  says it's gone, which makes the same exits 5.7 to 7.5 minutes
  ([control.md](control.md#estimating-someone-home-the-wasp-in-a-box))
- The doorbell swallowed the door. Seeing someone at the door started a fixed seven-second wait for
  the door to open, and since the automation runs one at a time, the door actually opening two
  seconds later was dropped. It waits for the door now, seven seconds at most
- Day switched off the lamps with someone home, and they got switched straight back on by hand. Day
  keeps them on, and a harsh kitchen ceiling only comes on when someone asks
  ([routines.md](routines.md#the-four-layers))
- A colour lamp came home cold. Arriving before the clock said Evening, the welcome look turned it on
  with no colour, so it came back at the morning look's 4000 K. It borrows the mode's colour now
- The GPS said home from just outside. The phone was in the zone but not on the Wi-Fi, nothing
  opened the door, and the 15-minute fallback lit the empty flat until the door really opened, the
  best part of an hour later. The fallback is only for a door sensor that isn't answering now, and a
  door that opens late still counts ([routines.md](routines.md#leaving-and-arriving))
- Away by hand skipped leaving. Away picked in the app on the way out left the wake-up's hold on the
  bedroom lamp, and the phone leaving minutes later found the house already Away, so nothing asked
  about the vacuum. Away by hand runs the leaving routine now
- A colour lamp dropped off Matter. Dozens of commands timed out over two days, so it stayed on
  through departures and missed a welcome, and twice it restarted itself at its own 4000 K and
  blended back for 40 minutes. Away gives a light that's still on a few more tries, and a restart
  goes straight back ([lighting.md](lighting.md#blending-not-switching))
- The vacuum's pause sent it home on the way out. Started from its own app as the door closed, the
  pause took it for the app's schedule and sent it back 10 seconds later. A start within three
  minutes of the front door gets to clean
- Calm jumped. At a fixed 9:30 PM it took the floor lamp to 40% amber in three seconds, whatever the
  bedtime, and the amber itself was a second dimming on top: below 2700 K a lot of colour lamps lose
  most of their light. Calm is the hour before the planned bedtime, on the curve, and the clock's mode
  changes blend in a small step a minute ([lighting.md](lighting.md#blending-not-switching))
- Two commands in one second. The gate waits for the arbiter to note a command before sending it, and
  it took any note from the last second as its own. With the blend tick and a mode change both
  reaching a lamp at the top of the minute, the second command went out on the first one's note and
  the lamp's answer looked like a hand at the switch (the test bench caught it). It waits for its own
  note now
- The GPS said "not home" while home. The last fix before walking in is often where you park, which
  can be further from the zone's centre than the zone reaches, and the phone doesn't send another
  while it's still. At 150 m that read as not home for the whole time I was in. The zone's size is
  `resident.home_radius_m`, and it wants to cover the parking
- "At the desk" chattered 14,000 times a day. A locked laptop charging drew 35 to 40 W, right on a
  35 W line, and every flip told the asleep filter someone was typing. That night the house never
  noticed I'd gone to sleep, and the lights stayed on until I left in the morning. 50 W with
  hysteresis now, and the line is a setting ([sensing.md](sensing.md#asleep))
- Switching a lamp off from the app made the house think someone was in. The wasp in a box counted
  any light changed by hand, the app included, so the house stayed occupied after I'd gone. Only the
  wall counts now ([control.md](control.md#estimating-someone-home-the-wasp-in-a-box))
- Home Assistant couldn't log in to an older Kasa plug, whatever login it got. Its firmware had moved
  to KLAP v2, which python-kasa handles from 0.11.0.1 while Home Assistant was still on 0.10.2. Next time
  an old TP-Link plug won't log in, I'm checking that before the password

## Choices that look like bugs

- No HACS, on purpose. Moonraker, the map card and the rest come straight from their GitHub
  releases, pinned by version and sha256 in `tools/ha-extras.sh`. HACS wants a GitHub login inside
  Home Assistant and updates from a menu, and then the repo isn't the truth anymore
- Nobody had put Kokoro in Home Assistant. It comes as a Python library, so `kokoro_wyoming.py` is the
  Wyoming bridge, about 150 lines. Parakeet got the same treatment
- Port 80, not 8123. This Home Assistant OS refuses the port every guide mentions

Next: back to [the README](../README.md), or [how the house decides](control.md).
