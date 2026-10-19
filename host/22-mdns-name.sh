#!/usr/bin/env bash
# Keeps the Hub answering as ha-hub.local. After a power cut avahi can come up before the Hub has
# its DHCP lease back, see something else claiming ha-hub.local (usually its own old record, still
# cached somewhere on the network) and quietly rename itself ha-hub-2.local. Everything that reaches
# the Hub by name breaks, and nothing says so. avahi has no setting to just not do that, so a timer
# checks the name every two minutes and restarts avahi when it has drifted, which by then wins the
# name back.
# From the PC: tools/push.sh host/22-mdns-name.sh
set -euo pipefail

cat >/usr/local/bin/mdns-name-check <<'EOF'
#!/bin/sh
# restarts avahi if it renamed itself after a name conflict (ha-hub-2 and so on)
want=$(hostname -s)
have=$(busctl call org.freedesktop.Avahi / org.freedesktop.Avahi.Server GetHostName 2>/dev/null | cut -d'"' -f2)
[ -z "$have" ] || [ "$have" = "$want" ] && exit 0
echo "avahi is calling itself $have.local instead of $want.local, restarting it"
systemctl restart avahi-daemon
EOF
chmod 755 /usr/local/bin/mdns-name-check

cat >/etc/systemd/system/mdns-name-check.service <<'EOF'
[Unit]
Description=Win back the Hub's mDNS name after a conflict
After=avahi-daemon.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/mdns-name-check
EOF

cat >/etc/systemd/system/mdns-name-check.timer <<'EOF'
[Unit]
Description=Check the Hub's mDNS name every two minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now mdns-name-check.timer >/dev/null 2>&1
echo "mdns-name-check.timer: $(systemctl is-active mdns-name-check.timer)"
