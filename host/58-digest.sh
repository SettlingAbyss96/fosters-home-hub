#!/usr/bin/env bash
# hub-digest: what Jarvis talks about in the welcome home (hub/hub_digest.py). It reads the sources
# in hub/digest.toml (or hub/digest.example.toml, if you haven't made your own) on its own schedule
# and keeps every item in SQLite, so nothing gets said twice, and Home Assistant asks it for a kit
# on the way in (ha/config/packages/digest.yaml). Python's standard library only. The database
# lives in /var/lib/hub-digest and survives reinstalls. Port 10230 is fenced to the Home Assistant
# VM like Kokoro's.
# From the PC: tools/push.sh host/58-digest.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)

install -D -m 755 "$here/hub/hub_digest.py" /usr/local/lib/ha-hub/hub_digest.py
sources="$here/hub/digest.toml"
[ -f "$sources" ] || sources="$here/hub/digest.example.toml"
install -D -m 644 "$sources" /usr/local/lib/ha-hub/digest.toml

cat >/etc/systemd/system/hub-digest.service <<'EOF'
[Unit]
Description=What Jarvis talks about when you get home
After=network-online.target digest-fence.service
Wants=network-online.target

[Service]
User=hub
StateDirectory=hub-digest
ExecStart=/usr/bin/python3 /usr/local/lib/ha-hub/hub_digest.py --db /var/lib/hub-digest/digest.db
Restart=always
RestartSec=30
Nice=10

[Install]
WantedBy=multi-user.target
EOF

# Only the Home Assistant VM (by MAC, so IPv4 and IPv6 alike) and the Hub itself
vm_mac=${VM_MAC:-$(virsh domiflist haos | awk '/bridge/ {print $5}')}
cat >/etc/ha-hub/digest-fence.nft <<EOF
table inet digest_fence
delete table inet digest_fence
table inet digest_fence {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport 10230 iif lo accept
    tcp dport 10230 ether saddr $vm_mac accept
    tcp dport 10230 reject with tcp reset
  }
}
EOF
cat >/etc/systemd/system/digest-fence.service <<'EOF'
[Unit]
Description=Only the Home Assistant VM can reach the digest
Before=hub-digest.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/ha-hub/digest-fence.nft
ExecStop=/usr/sbin/nft delete table inet digest_fence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable digest-fence hub-digest >/dev/null 2>&1
systemctl restart digest-fence hub-digest
echo "hub-digest: $(systemctl is-active hub-digest)"
