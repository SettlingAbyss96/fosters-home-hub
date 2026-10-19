#!/usr/bin/env bash
# Turns Wi-Fi off once br0 has proven itself on Ethernet. Two interfaces on one subnet only buys
# two default routes and the odd ARP surprise. The stanza gets commented out rather than deleted,
# so getting Wi-Fi back is just uncommenting it.
# Run it over the Ethernet address, not the Wi-Fi one, or it cuts off its own session.
# From the PC: ssh hub@ha-hub.local 'sudo bash -s' < host/21-wifi-off.sh
set -euo pipefail

wifi=wlp2s0

ip -4 addr show br0 | grep -q inet || { echo "br0 has no address, leaving Wi-Fi alone"; exit 1; }

ifdown "$wifi" 2>/dev/null || ip link set "$wifi" down
sed -i -E "/^(allow-hotplug|auto|iface) $wifi/,/^[[:space:]]*$/ s/^([^#])/#\1/" /etc/network/interfaces

grep -q -E "^[^#].*$wifi" /etc/network/interfaces && { echo "Wi-Fi stanza still active"; exit 1; }
echo "Wi-Fi off, stanza commented out in /etc/network/interfaces"
