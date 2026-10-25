# What stays home

*Where every secret lives, what leaves the house and to whom, and what to check before pushing a
fork anywhere public. Level 1.*

The way this goes wrong is boring and permanent: someone forks the repo to keep their own changes,
commits `house.toml` along with everything else because `git add .` doesn't ask, pushes it, and
now their Wi-Fi's name, their addresses and the iCal link that shows when they're out are on GitHub,
where even a force-push doesn't really take them back. So the repo is laid out to make that hard to
do by accident, and there's a check for the rest, and none of it is clever, it's mostly just keeping
the house in three files that git never sees and everything else generic.

## The three files that are yours

| File | What's in it |
|---|---|
| `house.toml` | your rooms, devices, addresses, your Wi-Fi's name, the calendar address |
| `ha/context/about.local.md` | what Jarvis knows about the household: who lives here, how to talk to them |
| `hub/parakeet-words.local.txt` | the words you say that speech to text should lean towards: names, places |

All three are in `.gitignore`, and so is everything made from them (`ha/config/house/`, the
generated dashboard). Back them up somewhere, they're the only parts of the house that aren't in
Home Assistant or in here.

## Where the secrets live

None of these is ever in the repo or in `house.toml`:

| Secret | Where it lives |
|---|---|
| Home Assistant's long-lived token | `~/.config/ha-hub/token` on your computer (`tools/ha.py` reads it and never prints it) |
| The broker login the Hub's services use | `/etc/ha-hub/mqtt.env` on the Hub, readable by root and `hub` only, and in the Mosquitto app |
| ESPHome's Wi-Fi, API key and update password | `/opt/ha-hub/esphome/secrets.yaml` on the Hub, made by `host/78-esphome.sh` |
| The cloud agent's API key | inside Home Assistant, in the provider's integration |
| The Oura app's client ID and secret | inside Home Assistant, under Application credentials |
| HASS.Agent's token and MQTT login | on the computer, typed into HASS.Agent's own setup |
| The backup encryption key | yours, from Home Assistant's backup settings |

## What leaves the house, and to whom

Most of it doesn't leave at all. The mics are processed on the Hub: wake word, echo cancelling and
the end-of-turn model run on the satellite, speech to text is Parakeet on the Hub, the voice is
Kokoro on the Hub. No audio goes anywhere and nothing is recorded, unless you turn on Home
Assistant's own debug recordings, which this repo doesn't. What does go out:

| What | To whom | When |
|---|---|---|
| What you said after the wake word, as text, plus the prompt (`about.md`, `about.local.md`) and the names and states of every entity exposed to voice | your cloud agent's provider | a question the built-in sentences don't cover, the welcome home, the morning briefing |
| Searches the agent decides to run | the provider's search | news, anything you ask about the world |
| Your home's location | the weather service (met.no by default) | every forecast |
| The phone's location | your Home Assistant, through Home Assistant Cloud or whatever you use to reach it from outside | as the phone reports |
| A box around home, its four corners and nothing else | OpenStreetMap's Overpass API, for the journal's map of places ([journal.md](journal.md)) | once a month, if the journal's on |
| Busy or free, nothing else | nowhere: it's your calendar's free/busy feed coming in | every few minutes |
| Sleep and activity | Oura's API, your own account | if you use the ring |

Each exposed entity is a line in every request to the agent, which is why the deploy exposes a
short list on purpose and hides the plumbing (the control layer's insides, the phone's own
sensors, the scripts that only the house calls). `about.local.md` goes with every request too, so
it's worth writing it the way you'd brief someone you trust but don't know well.

## What's fenced on the network

- The speech engines' ports (Kokoro 10210, Parakeet 10310, and Ollama's 11434 if it's on), the
  digest's 10230 and the journal's 10231 answer only the Home Assistant VM, by its MAC address, and
  the Hub itself. Everyone else gets a TCP reset. nftables, one small table each, in the host scripts
- Where you've been stays on the Hub. The journal matches positions to places against its own copy
  of the map, writes its questions from templates, and keeps the answers in its database and in
  `/config/journal`, so no position, place name or answer goes to the cloud agent or anyone else
- The kiosk's Chromium debugging port is bound to 127.0.0.1, so only the Hub can drive it
- The ESP32 nodes talk to Home Assistant over ESPHome's encrypted API, and update only with their
  password
- Moonraker, if you have a Klipper printer, trusts your whole network by default. That's Moonraker's
  setting, not this repo's, and worth knowing: anything on your Wi-Fi can drive the printer

## Faces at the door

A doorbell that recognises faces does it itself, on the doorbell, from the faces you added in its
app. Home Assistant only gets "this face is at the door" as an on or off. The names in the
entities come from the doorbell's app, so they're never written in the repo. And nothing serious
hangs on a match: a recognised face only confirms an arrival the phone already started, and it's
never announced as certain.

## Before you push a fork

```bash
python tools/privacy_check.py
```

It reads every file git would commit and stops on the three files above being committed, on any
value from your `house.toml` turning up in a committed file, and on anything shaped like a token or
a private key. It also lists private addresses, MACs and emails for you to look at, since some of
those are fine. It can't know everything private to you (a friend's name typed into a comment, say),
so read your diff too. If something did get pushed, rotating it (a new token, a new Wi-Fi password)
is the fix that actually works; rewriting history only hides it from people who haven't looked yet.

What I'd like to add when there's time: the same check as a pre-push hook in the repo, so it runs
without anyone remembering to.
