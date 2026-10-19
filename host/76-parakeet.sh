#!/usr/bin/env bash
# parakeet-wyoming: Parakeet speech-to-text for Home Assistant (hub/parakeet_wyoming.py), all local.
# It replaced Whisper in the VM: the same accuracy on my own recordings, a bit better even, and the
# words are ready about 0.4 s after I stop talking instead of 2.9 s (docs/voice.md).
# The house's own words (names, brands, rooms) get a boost while it decodes: hub/parakeet-words.txt
# has the ones every house running this has, and hub/parakeet-words.local.txt yours, which git
# never sees (people's names, the places you talk about).
# Pinned: the Python packages by version, the model by sha256. Port 10310 is fenced to the Home
# Assistant VM like Kokoro's. ha-apps.sh adds it to Home Assistant over Wyoming.
# From the PC: tools/push.sh host/76-parakeet.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
here=$(cd "$(dirname "$0")/.." && pwd)
dir=/opt/ha-hub/parakeet
model=sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8
sha=157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad

apt-get install -y -qq --no-install-recommends python3-venv bzip2 >/dev/null
install -d -o hub -g hub "$dir"
[ -x "$dir/venv/bin/python" ] || sudo -u hub python3 -m venv "$dir/venv"
sudo -u hub "$dir/venv/bin/pip" install -q --disable-pip-version-check \
  sherpa-onnx==1.13.8 wyoming==1.10.2 numpy==2.5.4

if [ ! -f "$dir/model/tokens.txt" ]; then
  tmp=$(sudo -u hub mktemp -d)
  sudo -u hub curl -fsSL -o "$tmp/m.tar.bz2" "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$model.tar.bz2"
  echo "$sha  $tmp/m.tar.bz2" | sha256sum -c --quiet - || { rm -rf "$tmp"; echo "checksum mismatch on $model"; exit 1; }
  sudo -u hub tar xjf "$tmp/m.tar.bz2" -C "$tmp"
  rm -rf "$dir/model" && mv "$tmp/$model" "$dir/model" && rm -rf "$tmp" "$dir/model/test_wavs"
fi

install -D -m 755 "$here/hub/parakeet_wyoming.py" /usr/local/lib/ha-hub/parakeet_wyoming.py
cat "$here/hub/parakeet-words.txt" "$here/hub/parakeet-words.local.txt" 2>/dev/null \
  | grep -v -e '^#' -e '^[[:space:]]*$' | sort -u >/tmp/parakeet-words.txt
install -D -m 644 /tmp/parakeet-words.txt /usr/local/lib/ha-hub/parakeet-words.txt
rm -f /tmp/parakeet-words.txt

cat >/etc/systemd/system/parakeet-wyoming.service <<'EOF'
[Unit]
Description=Parakeet speech-to-text over Wyoming (Jarvis's ears)
After=network-online.target parakeet-fence.service
Wants=network-online.target

[Service]
User=hub
ExecStart=/opt/ha-hub/parakeet/venv/bin/python /usr/local/lib/ha-hub/parakeet_wyoming.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Only the Home Assistant VM (by MAC, so IPv4 and IPv6 alike) and the Hub itself
vm_mac=${VM_MAC:-$(virsh domiflist haos | awk '/bridge/ {print $5}')}
cat >/etc/ha-hub/parakeet-fence.nft <<EOF
table inet parakeet_fence
delete table inet parakeet_fence
table inet parakeet_fence {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport 10310 iif lo accept
    tcp dport 10310 ether saddr $vm_mac accept
    tcp dport 10310 reject with tcp reset
  }
}
EOF
cat >/etc/systemd/system/parakeet-fence.service <<'EOF'
[Unit]
Description=Only the Home Assistant VM can reach Parakeet
Before=parakeet-wyoming.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/ha-hub/parakeet-fence.nft
ExecStop=/usr/sbin/nft delete table inet parakeet_fence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable parakeet-fence parakeet-wyoming >/dev/null 2>&1
systemctl restart parakeet-fence parakeet-wyoming
echo "parakeet-wyoming: $(systemctl is-active parakeet-wyoming)"
