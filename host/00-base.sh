#!/usr/bin/env bash
# Base packages on a fresh Debian 13 netinst. Safe to rerun.
# From the PC: ssh hub@ha-hub.local 'sudo bash -s' < host/00-base.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get full-upgrade -y -qq
apt-get install -y -qq curl git jq htop alsa-utils pciutils usbutils intel-microcode avahi-daemon

[ -f /var/run/reboot-required ] && echo "reboot required" || true
