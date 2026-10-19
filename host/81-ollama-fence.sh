#!/usr/bin/env bash
# Only Home Assistant gets to use Ollama. It has to listen on the LAN because Home Assistant lives
# in the VM on its own address, and Ollama has no login of its own, so without this anything on
# the home network could run the model (and keep the Hub's CPU pinned while it does).
#
# Matches the VM by its MAC rather than its IP, so it holds over IPv4 and IPv6 and doesn't care
# what the router does. Everything else gets a TCP reset rather than a silent drop, so a client
# trying the wrong address family falls back right away instead of hanging. Its own nftables
# table in its own unit, so it doesn't fight /etc/nftables.conf (which flushes everything).
# From the PC: tools/push.sh host/81-ollama-fence.sh
set -euo pipefail
vm_mac=${VM_MAC:-$(virsh domiflist haos | awk '/bridge/ {print $5}')}
[ -n "$vm_mac" ] || { echo "can't find the haos VM's MAC, set VM_MAC"; exit 1; }

install -d /etc/ha-hub
cat >/etc/ha-hub/ollama-fence.nft <<EOF
table inet ollama_fence
delete table inet ollama_fence
table inet ollama_fence {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport 11434 iif lo accept
    tcp dport 11434 ether saddr $vm_mac accept
    tcp dport 11434 reject with tcp reset
  }
}
EOF

cat >/etc/systemd/system/ollama-fence.service <<'EOF'
[Unit]
Description=Only the Home Assistant VM can reach Ollama
Before=ollama.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/ha-hub/ollama-fence.nft
ExecStop=/usr/sbin/nft delete table inet ollama_fence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ollama-fence >/dev/null 2>&1
systemctl restart ollama-fence
nft list table inet ollama_fence
