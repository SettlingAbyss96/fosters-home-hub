#!/usr/bin/env bash
# hub-ring: the LED ring as Jarvis's status light (hub/hub_ring.py). Off while waiting, green while
# listening, white while thinking and talking, red when muted or when a request fails. Needs the
# voice satellite's peripheral API from 70-voice.sh.
# From the PC: tools/push.sh host/72-ring.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
here=$(cd "$(dirname "$0")/.." && pwd)

apt-get install -y -qq --no-install-recommends python3-usb python3-websockets >/dev/null
install -D -m 755 "$here/hub/hub_ring.py" /usr/local/lib/ha-hub/hub_ring.py

cat >/etc/systemd/system/hub-ring.service <<'EOF'
[Unit]
Description=Hub LED ring follows the voice assistant
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/ha-hub/hub_ring.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hub-ring >/dev/null 2>&1
systemctl restart hub-ring
echo "hub-ring: $(systemctl is-active hub-ring)"
