#!/usr/bin/env bash
# hub-journal: Jarvis asking how it went once you're home (hub/hub_journal.py). Home Assistant sends
# it every phone position (ha/config/packages/journal.yaml), it works out where you stayed and what
# kind of place it was from a monthly copy of OpenStreetMap around home, and it hands Home Assistant
# a question after the welcome home. The questions come from hub/journal.toml (or
# hub/journal.example.toml, if you haven't made your own). The answers are kept in SQLite in
# /var/lib/hub-journal, which survives reinstalls, and in Home Assistant's /config/journal. Python's
# standard library only. Port 10231 is fenced to the Home Assistant VM like the digest's.
# From this computer: tools/push.sh host/59-journal.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)

install -D -m 755 "$here/hub/hub_journal.py" /usr/local/lib/ha-hub/hub_journal.py
questions="$here/hub/journal.toml"
[ -f "$questions" ] || questions="$here/hub/journal.example.toml"
install -D -m 644 "$questions" /usr/local/lib/ha-hub/journal.toml

cat >/etc/systemd/system/hub-journal.service <<'EOF'
[Unit]
Description=Jarvis asking how it went, and keeping the answers
After=network-online.target journal-fence.service
Wants=network-online.target

[Service]
User=hub
StateDirectory=hub-journal
StateDirectoryMode=0700
ExecStart=/usr/bin/python3 /usr/local/lib/ha-hub/hub_journal.py --db /var/lib/hub-journal/journal.db
Restart=always
RestartSec=30
Nice=10

[Install]
WantedBy=multi-user.target
EOF

# Only the Home Assistant VM (by MAC, so IPv4 and IPv6 alike) and the Hub itself
vm_mac=${VM_MAC:-$(virsh domiflist haos | awk '/bridge/ {print $5}')}
cat >/etc/ha-hub/journal-fence.nft <<EOF
table inet journal_fence
delete table inet journal_fence
table inet journal_fence {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport 10231 iif lo accept
    tcp dport 10231 ether saddr $vm_mac accept
    tcp dport 10231 reject with tcp reset
  }
}
EOF
cat >/etc/systemd/system/journal-fence.service <<'EOF'
[Unit]
Description=Only the Home Assistant VM can reach the journal
Before=hub-journal.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/ha-hub/journal-fence.nft
ExecStop=/usr/sbin/nft delete table inet journal_fence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable journal-fence hub-journal >/dev/null 2>&1
systemctl restart journal-fence hub-journal
echo "hub-journal: $(systemctl is-active hub-journal)"
