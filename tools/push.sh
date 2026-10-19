#!/usr/bin/env bash
# Copies host/, hub/ and tools/ to ~/ha-hub on the Hub, then runs the given host scripts there,
# in order, as root.
#   tools/push.sh host/50-screen.sh
# The Hub is hub.ssh in house.toml (hub@ha-hub.local without one), and HUB overrides it. The few
# host settings that live in house.toml go along as environment variables: the wake word for
# 70-voice.sh and Kokoro's voice for 74-kokoro.sh. Everything else the scripts work out on the Hub.
set -euo pipefail
cd "$(dirname "$0")/.."
target=${HUB:-$(python tools/house.py get hub.ssh hub@ha-hub.local)}
wake=$(python tools/house.py get voice.wake_word hey_jarvis)
voice=$(python tools/house.py get voice.tts_voice bm_daniel)
case "$wake$voice" in *[!a-z0-9_]*) echo "voice.wake_word and voice.tts_voice are letters, digits and _ only"; exit 1 ;; esac

tar -c host hub tools | ssh "$target" 'rm -rf ~/ha-hub && mkdir -p ~/ha-hub && tar -x -C ~/ha-hub'
for s in "$@"; do
  echo "== $s"
  ssh "$target" "sudo env WAKE_MODEL=$wake KOKORO_VOICE=$voice bash ~/ha-hub/$s"
done
