#!/usr/bin/env bash
# Linux Voice Assistant: the voice satellite. Listens for "Hey Jarvis" on the echo-cancelled mic
# from 60-audio.sh, then streams to Home Assistant, which adds it through the ESPHome integration
# (port 6053). Runs as a user service of hub, next to PipeWire.
# LVA has no releases yet, so it's pinned to a commit that's been tried on this box.
# No chimes. The wake and thinking sounds are swapped for a 50 ms silent file, and the LED ring
# says what's going on instead (hub_ring.py, host/72-ring.sh). --listen-during-wake-sound starts
# streaming the moment the wake word lands, so "Hey Jarvis, what's the weather" works in one breath
# without waiting for anything. The peripheral API the ring listens on stays on 127.0.0.1.
# From the PC: tools/push.sh host/70-voice.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
user=hub
uid=$(id -u "$user")
home=$(getent passwd "$user" | cut -d: -f6)
ref=${LVA_REF:-b49fd8d}
# the wake word model the satellite listens with (LVA's own list: hey_jarvis, okay_nabu, hey_mycroft...)
wake=${WAKE_MODEL:-hey_jarvis}
here=$(cd "$(dirname "$0")/.." && pwd)
dir=$home/linux-voice-assistant

apt-get install -y -qq --no-install-recommends \
  git build-essential python3-venv python3-dev libmpv-dev avahi-utils

as_user() { sudo -u "$user" XDG_RUNTIME_DIR=/run/user/$uid "$@"; }

if [ ! -d "$dir/.git" ]; then
  as_user git clone -q https://github.com/OHF-Voice/linux-voice-assistant.git "$dir"
fi
as_user git -C "$dir" fetch -q origin
if [ "$(as_user git -C "$dir" rev-parse --short HEAD)" != "$ref" ] || [ ! -x "$dir/.venv/bin/python" ]; then
  as_user git -C "$dir" checkout -q "$ref"
  as_user bash -c "cd '$dir' && python3 script/setup >/tmp/lva-setup.log 2>&1"
fi
# Our patches on top of the pinned commit, put back fresh every run:
#   lva-followup.patch  after a spoken answer the mic stays open for a follow-up without the wake
#                       word, for as long as the exchange suggests (see LVA_WINDOW_* below), and
#                       closes quietly if nobody speaks. Closing phrases ("thank you", "that's all")
#                       end it. Stock LVA only reopens the mic when the answer ends in a question mark.
#                       Also a watchdog that stops an answer still "playing" long past its length,
#                       and silence when Jarvis answers "(no reply)" (speech that wasn't for it)
#   lva-player.patch    a spoken answer whose stream ends in an error counts as finished. Stock LVA
#                       only counted a clean end, so a broken-off answer left Jarvis stuck in
#                       "responding" with the ring white until a restart
#   lva-wakelog.patch   every "Hey Jarvis" that came close but didn't fire goes in the journal with
#                       how close, and so does every one that did. Plus the loudest thing the mic
#                       heard every 15 minutes. A miss used to leave nothing behind at all:
#                       journalctl --user -u linux-voice-assistant | grep wake
#   lva-endofturn.patch a finished sentence ends the turn straight away instead of waiting out
#                       Home Assistant's silence timer: Smart Turn v3.2 listens at each pause
#                       (hub/lva_end_of_turn.py, docs/voice.md). Its models are below, pinned
#   lva-preroll.patch   "Hey Jarvis, who am I" in one breath lost its start: the satellite now
#                       sends a quarter second from before the wake word, and holds the audio
#                       until Home Assistant is listening, which used to throw the first bit away
as_user git -C "$dir" checkout -q -- linux_voice_assistant/satellite.py linux_voice_assistant/player/libmpv.py linux_voice_assistant/__main__.py
as_user git -C "$dir" apply "$here/host/patches/lva-followup.patch"
as_user git -C "$dir" apply "$here/host/patches/lva-player.patch"
as_user git -C "$dir" apply "$here/host/patches/lva-wakelog.patch"
as_user git -C "$dir" apply "$here/host/patches/lva-endofturn.patch"
as_user git -C "$dir" apply "$here/host/patches/lva-preroll.patch"
as_user install -m 644 "$here/hub/lva_end_of_turn.py" "$dir/linux_voice_assistant/end_of_turn.py"
as_user "$dir/.venv/bin/pip" install -q --disable-pip-version-check onnxruntime==1.31.0

# Smart Turn and the Silero speech detector it works with, both small (8.7 MB and 2.3 MB)
turn=$home/.local/share/lva-turn
as_user install -d "$turn"
fetch() {  # fetch FILE URL SHA256
  echo "$3  $turn/$1" | sha256sum -c --quiet - >/dev/null 2>&1 && return
  as_user curl -fsSL -o "$turn/$1.tmp" "$2"
  echo "$3  $turn/$1.tmp" | sha256sum -c --quiet - || { rm -f "$turn/$1.tmp"; echo "checksum mismatch on $1"; exit 1; }
  mv "$turn/$1.tmp" "$turn/$1"
}
fetch smart-turn-v3.2-cpu.onnx \
  https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx \
  2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f
fetch silero_vad.onnx https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.3/src/silero_vad/data/silero_vad.onnx \
  1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3

install -d -o "$user" -g "$user" "$home/.config/systemd/user" "$home/.config/linux-voice-assistant"
# the silence that stands in for every chime
python3 -c "
import wave
w = wave.open('$home/.config/linux-voice-assistant/silence.wav', 'wb')
w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(1600))
w.close()"
chown "$user:$user" "$home/.config/linux-voice-assistant/silence.wav"
cat >"$home/.config/systemd/user/linux-voice-assistant.service" <<'EOF'
[Unit]
Description=Linux Voice Assistant (the Hub's voice satellite)
After=pipewire.service pipewire-pulse.service wireplumber.service
Wants=pipewire-pulse.service

[Service]
WorkingDirectory=%h/linux-voice-assistant
ExecStart=%h/linux-voice-assistant/.venv/bin/python -m linux_voice_assistant \
  --name "Hub 500 Voice" \
  --audio-input-device "Hub mic (echo cancelled)" \
  --audio-output-device pipewire/hub_speaker \
  --wake-model hey_jarvis \
  --listen-during-wake-sound \
  --wakeup-sound %h/.config/linux-voice-assistant/silence.wav \
  --processing-sound %h/.config/linux-voice-assistant/silence.wav \
  --peripheral-host 127.0.0.1 \
  --preferences-file %h/.config/linux-voice-assistant/preferences.json
# Follow-up window lengths (seconds): after a one-shot answer or a finished task, mid-conversation,
# and when Jarvis asked something or didn't manage it. Nothing after "thank you" and friends.
# LISTEN_CAP stops room noise holding one turn open (it once held on for 27 s)
Environment=LVA_WINDOW_SHORT=2.5 LVA_WINDOW_MEDIUM=5 LVA_WINDOW_LONG=8 LVA_LISTEN_CAP=15
# Smart Turn's models. Empty turns it off and Home Assistant's silence timer ends every turn again
Environment=LVA_END_OF_TURN=%h/.local/share/lva-turn
# Seconds of mic from before the wake word that go with the turn
Environment=LVA_PREROLL=0.3
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
sed -i "s/--wake-model hey_jarvis/--wake-model $wake/" "$home/.config/systemd/user/linux-voice-assistant.service"
chown "$user:$user" "$home/.config/systemd/user/linux-voice-assistant.service"

as_user systemctl --user daemon-reload
as_user systemctl --user enable linux-voice-assistant >/dev/null 2>&1
as_user systemctl --user restart linux-voice-assistant
echo "linux-voice-assistant: $(as_user systemctl --user is-active linux-voice-assistant) at $(as_user git -C "$dir" rev-parse --short HEAD)"
