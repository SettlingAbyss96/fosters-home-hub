# Setting it up

*From a Hub 500 in its box to Jarvis answering, in the order that works. The steps are exact; the
bits between them say why, and what tends to go wrong.*

The whole thing runs on the one box, so most of this is getting Debian onto the Hub and then
letting the scripts in `host/` do their part, after which Home Assistant comes up in a VM and
`tools/ha-apps.sh` makes it match your `house.toml`. Plan an evening for the first pass, and expect
to run `tools/ha-apps.sh` several more times as you add devices, which is fine, it's built to be
rerun. I've done the rebuild from scratch on my own Hub and written it down as I went, but I
haven't watched someone else go through it on theirs yet, so if a step here doesn't match what your
box does, that's worth an issue.

## What you need

- A Lenovo ThinkSmart Hub 500 ([hardware.md](hardware.md) has what's inside and how Linux takes it)
- An Ethernet cable to your router. Not optional: Wi-Fi can't be bridged, and the VM needs to be on
  the network with its own address ([architecture.md](architecture.md))
- A USB stick for the Debian installer, and a USB keyboard for the install itself
- A computer to drive it from, with `bash`, `ssh`, `git` and Python 3.11 or newer. On Windows that's
  Git Bash and Python from python.org; macOS and Linux have the first three already
- Optional but worth it: 16 GB of RAM (two 8 GB DDR4-2400 SO-DIMMs, 2400 is the CPU's ceiling).
  It runs on the stock 8 GB, just with very little to spare once the speech engines are loaded

## 1. Two addresses on your router

Before anything, give your router a reservation for the Hub and, once it exists, the VM.
Home Assistant reaches the Hub's speech engines by address, and a Hub that comes back from a power
cut on a different address is a deaf assistant. [network.md](network.md) has the reasoning and a
plan you can borrow.

## 2. Debian on the Hub

1. Debian 13 netinst on the USB stick, then boot the Hub from it (F12 for the boot menu)
2. Hostname `ha-hub`, user `hub`, and leave the root password blank so `hub` gets sudo
3. Guided partitioning, the whole NVMe, all files in one partition. No LVM and no encryption: a
   passphrase prompt after a power cut means a wall panel that stays dark until someone types it
4. Software: only "SSH server" and "standard system utilities". No desktop, the kiosk brings its own
5. On the Hub, so the scripts can run over SSH without a password prompt:

   ```bash
   echo "hub ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/hub
   ```

## 3. The repo and your house.toml

On your computer:

```bash
git clone https://github.com/SettlingAbyss96/fosters-home-hub.git
```

```bash
cd fosters-home-hub && cp house.example.toml house.toml
```

For now only `[hub]` matters: `ssh` (leave it as `hub@ha-hub.local` once mDNS works, or put the
Hub's address in for the first few steps) and `address`. The rest of `house.toml` gets filled in as
the house does. It never leaves your computer, `.gitignore` sees to that.

## 4. The host scripts

Copy your SSH key across and run the first three. Until avahi is in (the first script installs it),
use the Hub's address instead of `ha-hub.local`:

```bash
cat ~/.ssh/id_ed25519.pub | ssh hub@ha-hub.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

```bash
for s in host/00-base.sh host/10-virt.sh host/20-bridge.sh; do ssh hub@ha-hub.local 'sudo bash -s' < "$s"; done
```

No key yet? `ssh-keygen -t ed25519` makes one. Then reboot the Hub with the Ethernet cable in, so
`br0` comes up, and push the rest:

```bash
tools/push.sh host/21-wifi-off.sh host/22-mdns-name.sh host/30-haos-vm.sh host/40-kiosk.sh host/50-screen.sh host/55-stats.sh host/60-audio.sh host/70-voice.sh host/72-ring.sh host/74-kokoro.sh host/76-parakeet.sh
```

That's the VM, the touchscreen, the screen and stats services, the echo-cancelled audio, the voice
satellite and the LED ring, and both speech engines. Each script says what it does at the top, and
each is safe to run again. `host/90-test-env.sh` is the test bench ([testing.md](testing.md)), about
900 MB of Home Assistant on its own Python; worth it if you'll change the packages, skippable if you
won't (then deploy with `SKIP_TESTS=1`). `host/78-esphome.sh` is only for the ESP32 nodes
([esp32.md](esp32.md)), and `host/80-ollama.sh` only for a local model.

## 5. Home Assistant

A few minutes later Home Assistant is at `http://homeassistant.local`. Port 80, not the 8123 every
guide mentions, which this version refuses. Now's the time for the VM's address reservation on the
router, while you remember.

1. Onboard it (or restore a backup)
2. Log the kiosk in: on the Hub's touchscreen, sign in with a user made for the wall. It keeps the
   session from then on
3. Make a long-lived token (your profile, Security, Long-lived access tokens) and save it on your
   computer as `~/.config/ha-hub/token`. It never goes in the repo or in `house.toml`

## 6. The phone

Install the Home Assistant companion app, and before you sign in, set its device name to `Phone`
(Settings, Companion app). Every phone entity the house reads is then `sensor.phone_...`, and the
notify service is `notify.mobile_app_phone`, which can't be renamed later. Give it location
permission "always", and make a person in Home Assistant (Settings, People) with the phone attached.
That person goes in `house.toml` as `resident.person`.

Presence away from home needs Home Assistant reachable from outside. Home Assistant Cloud is the
easy way; anything else that gets the app through works too. The phone Shortcuts in
[sensing.md](sensing.md#reading-the-phone-through-shortcuts) make leaving and arriving much quicker,
and they're optional.

## 7. The cloud agent

Optional, and the one part that costs money. Without it, Jarvis answers the built-in sentences and
this repo's own (lights, modes, the TV, reminders, the wake-up) and nothing looser. With it, any
question gets an answer, and the welcome home and the morning briefing get written by it.

Add your provider's integration in Home Assistant (Settings, Devices and services, Add
integration), then its conversation agent, and put that agent's entity id in `house.toml` as
`voice.cloud_agent`. The deploy renames it `conversation.jarvis_cloud` and gives it
`ha/context/about.md` as its prompt. Pick its model and its settings in the provider's own options:
a fast model with low reasoning effort suits a voice, and web search makes the news parts work.
Copy `ha/context/about.local.example.md` to `about.local.md` and tell it who lives here.

## 8. Your devices

Pair them the normal way (Matter lights from the companion app's "Add Matter device", the rest
from their integrations), then describe them in `house.toml`: the rooms, a `[[light]]` table per
light with its layer and jobs, and `[devices]` for the things with standard names.
[devices.md](devices.md) has what each part of the house needs, and the names it expects.

## 9. Deploy

```bash
tools/ha-apps.sh
```

```bash
tools/ha-extras.sh
```

`ha-apps.sh` checks `house.toml`, runs the tests, then sets up everything it can and says what it
couldn't yet. `ha-extras.sh` installs the community pieces listed in `extras.install`, pinned by
version and checksum. Run `ha-apps.sh` once more after the extras, so the dashboard picks up the
cards. Then say "Hey Jarvis, what time is it?" to the Hub.

If the deploy stops at "a scenario failed", the bench caught something in the packages, and the
house you have is untouched. `SKIP_TESTS=1 tools/ha-apps.sh` goes ahead anyway, which I'd only do
when the bench itself is what's broken.

## 10. After that

- `git pull`, then `tools/ha-apps.sh`, picks up changes here. Host scripts that changed get rerun
  with `tools/push.sh`
- A new device: pair it, add it to `house.toml`, `tools/ha-apps.sh`
- A backup: Home Assistant's own, with Matter Server and Mosquitto in it (the deploy adds both, or
  a restore loses every Matter pairing). Keep `house.toml` and `about.local.md` somewhere safe too,
  they're the only parts that aren't in Home Assistant or here

How long the first `ha-apps.sh` takes depends mostly on Whisper downloading its model, about ten
minutes on mine.
