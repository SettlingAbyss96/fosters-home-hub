#!/usr/bin/env bash
# Puts the Ethernet port on a bridge (br0) so the HAOS VM shows up on the LAN with its own IP.
# Wi-Fi can't be bridged, which is the whole reason the Hub needs a cable.
# The Wi-Fi config is left alone so the Hub stays reachable if the bridge doesn't come up.
# Takes effect on the next boot (or ifup br0 with a cable in).
# From the PC: ssh hub@ha-hub.local 'sudo bash -s' < host/20-bridge.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

eth=enp0s31f6
mac=$(cat /sys/class/net/$eth/address)

apt-get install -y -qq bridge-utils

# bridge_hw pins the bridge to the Ethernet MAC. Without it the bridge takes the lowest MAC of
# its ports, and libvirt's 52:54:00:... taps are lower, so the host's MAC (and DHCP lease) would
# change every time the VM starts.
cat >/etc/network/interfaces.d/br0 <<EOF
# Written by fosters-home-hub/host/20-bridge.sh
auto br0
iface br0 inet dhcp
    bridge_ports $eth
    bridge_hw $mac
    bridge_stp off
    bridge_fd 0
    bridge_maxwait 0
EOF

ifquery br0 >/dev/null && echo "br0 config OK, bridge MAC $mac"
