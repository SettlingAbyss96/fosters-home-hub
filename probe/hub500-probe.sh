#!/usr/bin/env bash
# ThinkSmart Hub 500 hardware probe.
#
# Run it from a Debian 13 live session, as the normal live user (not root),
# from the USB stick this file sits on:
#   bash hub500-probe.sh
#
# Nothing gets installed and the internal SSD is never touched. Everything lands
# in a hub500-probe-<timestamp> folder next to this script, so bring the stick
# back to the PC afterwards.

set -u

here="$(cd "$(dirname "$0")" && pwd)"
out="$here/hub500-probe-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"
log="$out/report.txt"

section() {
  printf '\n===== %s =====\n' "$*" >>"$log"
}

# run <cmd...>: append a command's output to the report, or note it's missing
run() {
  section "$*"
  if command -v "$1" >/dev/null 2>&1; then
    "$@" >>"$log" 2>&1
  else
    echo "(not installed: $1)" >>"$log"
  fi
}

echo "Collecting hardware info into $out ..."

# --- machine and firmware ---
section "dmi"
for f in sys_vendor product_name product_version product_family board_name \
         bios_vendor bios_version bios_date; do
  printf '%s: %s\n' "$f" "$(cat /sys/class/dmi/id/$f 2>/dev/null)" >>"$log"
done

section "boot mode"
if [ -d /sys/firmware/efi ]; then
  echo "UEFI" >>"$log"
  sb=/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c
  if [ -r "$sb" ]; then
    # last byte of the efivar is 1 when Secure Boot is on
    echo "SecureBoot byte: $(od -An -t u1 "$sb" | awk '{print $NF}')" >>"$log"
  fi
else
  echo "legacy BIOS" >>"$log"
fi

run uname -a
run lscpu
run free -h
run lsblk -o NAME,SIZE,MODEL,TRAN,TYPE
run sudo dmidecode -t memory

# --- buses ---
run lspci -nnk
run lsusb
run lsusb -t
section "lsusb -v (separate file)"
sudo lsusb -v >"$out/usb-verbose.txt" 2>&1 && echo "saved usb-verbose.txt" >>"$log"

# --- touchscreen and other input ---
run cat /proc/bus/input/devices
run ls -l /sys/bus/i2c/devices/
section "i2c device names"
grep -H . /sys/bus/i2c/devices/*/name >>"$log" 2>&1
run sudo libinput list-devices
section "loaded modules (touch, i2c, hid, sound)"
lsmod | grep -E -i 'i2c|hid|lpss|designware|snd|touch|sensor' >>"$log" 2>&1

# --- display ---
section "drm connectors"
for c in /sys/class/drm/card*-*; do
  [ -e "$c/status" ] || continue
  printf '%s: %s %s\n' "$(basename "$c")" "$(cat "$c/status")" \
    "$(head -n1 "$c/modes" 2>/dev/null)" >>"$log"
done

# --- audio ---
run cat /proc/asound/cards
run aplay -l
run arecord -l
section "usb audio stream formats (channel counts live here)"
for s in /proc/asound/card*/stream*; do
  [ -e "$s" ] || continue
  echo "--- $s" >>"$log"
  cat "$s" >>"$log"
done
run wpctl status
run pactl list short sinks
run pactl list short sources
section "pw-dump (separate file)"
pw-dump >"$out/pw-dump.json" 2>&1 && echo "saved pw-dump.json" >>"$log"

# --- network ---
run ip -br link

# --- kernel log ---
section "dmesg (separate file)"
sudo dmesg >"$out/dmesg.txt" 2>&1 && echo "saved dmesg.txt" >>"$log"

echo
echo "Info collected. Now the interactive audio tests."
echo

# --- speaker test ---
read -r -p "Speaker test: press Enter, you should hear 'front left' then 'front right'. "
speaker-test -c 2 -t wav -l 1 >>"$out/speaker-test.txt" 2>&1
echo "If that was silent, open Settings > Sound, pick the Lenovo/USB output and rerun later."
echo

# --- mic tests: record 5 s from every capture device ---
arecord -l 2>/dev/null | grep -E '^card [0-9]+:' | while read -r line; do
  card=$(echo "$line" | sed -E 's/^card ([0-9]+):.*/\1/')
  dev=$(echo "$line" | sed -E 's/.*device ([0-9]+):.*/\1/')
  name=$(echo "$line" | sed -E 's/^card [0-9]+: ([^ ]+).*/\1/')
  wav="$out/mic-card${card}-dev${dev}-${name}.wav"
  echo "Capture device: $line"
  read -r -p "Press Enter, then talk normally from across the room for 5 seconds. " </dev/tty
  arecord -D "plughw:${card},${dev}" -f S16_LE -r 16000 -c 2 -d 5 "$wav" \
    >>"$out/mic-test.txt" 2>&1 || echo "  recording failed, see mic-test.txt"
  if [ -s "$wav" ]; then
    echo "  playing it back..."
    aplay "$wav" >/dev/null 2>&1
  fi
  echo
done

echo "Done. Everything is in: $out"
echo "Also jot down: did touch work? did you hear the speaker? which recordings had your voice?"
