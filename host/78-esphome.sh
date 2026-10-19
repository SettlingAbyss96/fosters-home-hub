#!/usr/bin/env bash
# ESPHome on the Hub: the tool that builds the ESP32 sensor nodes in esphome/ and updates them over
# Wi-Fi, so nothing needs installing on the PC. The Hub does the compiling (a few minutes the first
# time, while it fetches the toolchain, seconds after). tools/esphome.sh drives it.
# The secrets (the Wi-Fi, the key Home Assistant talks to the nodes with, the update password) live
# in /opt/ha-hub/esphome/secrets.yaml, never in the repo. The two keys and the timezone (the
# Hub's own) get made here the first time; the Wi-Fi name and password are yours to type in.
# Pinned: ESPHome by version. The hub user goes in dialout, for flashing a node plugged into the Hub.
# From the PC: tools/push.sh host/78-esphome.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
dir=/opt/ha-hub/esphome

apt-get install -y -qq --no-install-recommends python3-venv >/dev/null
install -d -o hub -g hub "$dir" "$dir/work"
[ -x "$dir/venv/bin/python" ] || sudo -u hub python3 -m venv "$dir/venv"
sudo -u hub "$dir/venv/bin/pip" install -q --disable-pip-version-check esphome==2026.9.1
usermod -aG dialout hub

if [ ! -f "$dir/secrets.yaml" ]; then
  key=$(head -c 32 /dev/urandom | base64)
  ota=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
  umask 077
  cat >"$dir/secrets.yaml" <<EOF
# The ESP32 nodes' secrets. Not in the repo. The Wi-Fi name and password are still to fill in
wifi_ssid: "CHANGE_ME"
wifi_password: "CHANGE_ME"
api_key: "$key"
ota_password: "$ota"
timezone: "$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value)"
EOF
  chown hub:hub "$dir/secrets.yaml"
  echo "made $dir/secrets.yaml: the Wi-Fi name and password go in it before the first build"
fi
# secrets from before the nodes took their timezone from here
grep -q '^timezone:' "$dir/secrets.yaml" ||
  printf 'timezone: "%s"\n' "$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value)" >>"$dir/secrets.yaml"
echo "esphome $("$dir/venv/bin/esphome" version | awk '{print $2}')"
