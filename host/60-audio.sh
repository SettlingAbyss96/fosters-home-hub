#!/usr/bin/env bash
# PipeWire for user hub, with WebRTC echo cancellation between the Hub's own speakers and mics.
# The DSP doesn't cancel anything itself (speaker at -20 dBFS lands at -44.5 dBFS on the mics),
# so without this the wake word would hear every TTS reply and every song.
#
# Everything plays into "hub_speaker" (the canceller's reference) and listens on "hub_mic" (the
# cleaned mic). Both are the defaults, so Chromium, the voice satellite and anything else get
# cancellation without knowing about it. Speaker and mics share one USB clock, so no drift.
# From the PC: tools/push.sh host/60-audio.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
user=hub
uid=$(id -u "$user")

apt-get install -y -qq --no-install-recommends \
  pipewire pipewire-bin wireplumber pipewire-pulse pipewire-alsa libspa-0.2-modules pulseaudio-utils \
  rtkit

# PipeWire is a user service. Lingering keeps it (and the voice satellite) running with nobody
# logged in, which on a wall panel is always
loginctl enable-linger "$user"

# the Hub's one USB audio device, by its id. Every Hub 500 seen so far calls itself this, but it's
# looked up rather than trusted, and HUB_AUDIO overrides it
usb=${HUB_AUDIO:-$(ls /dev/snd/by-id 2>/dev/null | grep -m1 -o '^usb-Generic_USB_Audio_[A-Za-z0-9]*-00' || true)}
usb=${usb:-usb-Generic_USB_Audio_201405280001-00}
install -d /etc/pipewire/pipewire.conf.d
cat >/etc/pipewire/pipewire.conf.d/50-hub-echo-cancel.conf <<EOF
# Written by fosters-home-hub/host/60-audio.sh
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name   = aec/libspa-aec-webrtc
      audio.rate     = 48000
      audio.channels = 1
      audio.position = [ MONO ]
      aec.args = {
        webrtc.high_pass_filter = true
        webrtc.noise_suppression = true
        webrtc.gain_control = true
        webrtc.experimental_agc = true
      }
      capture.props = {
        node.name = "capture.hub_aec"
        target.object = "alsa_input.$usb.analog-stereo"
      }
      source.props = {
        node.name = "hub_mic"
        node.description = "Hub mic (echo cancelled)"
        priority.session = 2100
      }
      sink.props = {
        node.name = "hub_speaker"
        node.description = "Hub speaker"
        priority.session = 2100
      }
      playback.props = {
        node.name = "playback.hub_aec"
        target.object = "alsa_output.$usb.analog-stereo"
      }
    }
  }
]
EOF

# Hardware levels. The DSP ignores playback volume anyway, but the mic gain is real and it's
# already the weak link, so pin it at max
card=$(awk '/USB-Audio - USB Audio/ {print $1; exit}' /proc/asound/cards)
amixer -q -c "$card" sset Mic 100% cap || true

as_user() { sudo -u "$user" XDG_RUNTIME_DIR=/run/user/$uid "$@"; }
as_user systemctl --user enable pipewire.socket pipewire-pulse.socket wireplumber.service >/dev/null 2>&1
as_user systemctl --user restart pipewire pipewire-pulse wireplumber
for i in $(seq 1 20); do as_user pactl list short sources | grep -q hub_mic && break; sleep 1; done
as_user pactl set-default-sink hub_speaker
as_user pactl set-default-source hub_mic
echo "default sink: $(as_user pactl get-default-sink), default source: $(as_user pactl get-default-source)"
