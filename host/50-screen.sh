#!/usr/bin/env bash
# hub-screen: the panel's power and brightness (DDC/CI), the PIR and touch-to-wake, as Home
# Assistant entities over MQTT. Needs the Mosquitto app running with an ha-hub login whose
# password matches /etc/ha-hub/mqtt.env (this script creates that file on the first run).
# From the PC: tools/push.sh host/50-screen.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
here=$(cd "$(dirname "$0")/.." && pwd)

apt-get install -y -qq --no-install-recommends ddcutil python3-paho-mqtt

# ddcutil talks to the panel over /dev/i2c-*
echo i2c-dev >/etc/modules-load.d/i2c-dev.conf
modprobe i2c-dev

install -d -m 750 -o root -g hub /etc/ha-hub
if [ ! -f /etc/ha-hub/mqtt.env ]; then
  pass=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  printf 'MQTT_HOST=homeassistant.local\nMQTT_PORT=1883\nMQTT_USER=ha-hub\nMQTT_PASS=%s\n' "$pass" \
    >/etc/ha-hub/mqtt.env
  chown root:hub /etc/ha-hub/mqtt.env
  chmod 640 /etc/ha-hub/mqtt.env
  echo "new MQTT login written to /etc/ha-hub/mqtt.env, add it to the Mosquitto app"
fi

install -d -m 755 /var/lib/ha-hub
install -D -m 755 "$here/hub/hub_screen.py" /usr/local/lib/ha-hub/hub_screen.py

cat >/etc/systemd/system/hub-screen.service <<'EOF'
[Unit]
Description=Hub 500 screen, presence and touch wake over MQTT
After=network-online.target systemd-modules-load.service
Wants=network-online.target

[Service]
# ddcutil keeps a sleep-tuning cache under $HOME, which a system service doesn't have
Environment=HOME=/var/lib/ha-hub
ExecStart=/usr/bin/python3 /usr/local/lib/ha-hub/hub_screen.py
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hub-screen >/dev/null 2>&1
systemctl restart hub-screen
echo "hub-screen: $(systemctl is-active hub-screen)"
