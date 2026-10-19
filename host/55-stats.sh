#!/usr/bin/env bash
# hub-stats: the whole box's CPU, memory, temperatures and disk, split by part (VM, Ollama, kiosk,
# voice), as Home Assistant sensors over MQTT. Uses the broker login 50-screen.sh set up.
# From the PC: tools/push.sh host/55-stats.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
here=$(cd "$(dirname "$0")/.." && pwd)

[ -f /etc/ha-hub/mqtt.env ] || { echo "run host/50-screen.sh first, it writes the broker login"; exit 1; }
apt-get install -y -qq --no-install-recommends python3-paho-mqtt

install -D -m 755 "$here/hub/hub_stats.py" /usr/local/lib/ha-hub/hub_stats.py

# root, because per-process memory (smaps_rollup) of other users' processes needs it
cat >/etc/systemd/system/hub-stats.service <<'EOF'
[Unit]
Description=Hub 500 CPU, memory and temperatures over MQTT
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/ha-hub/hub_stats.py
Restart=always
RestartSec=10
Nice=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hub-stats >/dev/null 2>&1
systemctl restart hub-stats
echo "hub-stats: $(systemctl is-active hub-stats)"
