#!/usr/bin/env bash
# kokoro-wyoming: Kokoro text-to-speech for Home Assistant (hub/kokoro_wyoming.py), all local. It
# replaced Piper as Jarvis's voice: Piper's community Jarvis model is clear enough but a bit robotic,
# and Kokoro's British voices are in another league next to it, for about a second to the first
# word. Runs on the Hub rather than in the VM because that's where the spare CPU and memory are.
# KOKORO_VOICE picks the voice (bm_daniel to start, any of Kokoro's voice names works).
# Pinned: the Python packages by version, the model files by sha256. Port 10210 is fenced to the
# Home Assistant VM like Ollama's was. ha-apps.sh adds it to Home Assistant over Wyoming.
# From the PC: tools/push.sh host/74-kokoro.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
here=$(cd "$(dirname "$0")/.." && pwd)
dir=/opt/ha-hub/kokoro
voice=${KOKORO_VOICE:-bm_daniel}
release=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0

apt-get install -y -qq --no-install-recommends python3-venv >/dev/null
install -d -o hub -g hub "$dir"
[ -x "$dir/venv/bin/python" ] || sudo -u hub python3 -m venv "$dir/venv"
sudo -u hub "$dir/venv/bin/pip" install -q --disable-pip-version-check \
  kokoro-onnx==0.6.1 onnxruntime==1.31.0 wyoming==1.10.2 numpy==2.5.3 soundfile==0.14.0

fetch() {  # fetch FILE SHA256
  echo "$2  $dir/$1" | sha256sum -c --quiet - 2>/dev/null && return
  sudo -u hub curl -fsSL -o "$dir/$1.tmp" "$release/$1"
  echo "$2  $dir/$1.tmp" | sha256sum -c --quiet - || { rm -f "$dir/$1.tmp"; echo "checksum mismatch on $1"; exit 1; }
  mv "$dir/$1.tmp" "$dir/$1"
}
fetch kokoro-v1.0.int8.onnx 6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb
fetch voices-v1.0.bin bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d

install -D -m 755 "$here/hub/kokoro_wyoming.py" /usr/local/lib/ha-hub/kokoro_wyoming.py

cat >/etc/systemd/system/kokoro-wyoming.service <<'EOF'
[Unit]
Description=Kokoro text-to-speech over Wyoming (Jarvis's voice)
After=network-online.target kokoro-fence.service
Wants=network-online.target

[Service]
User=hub
ExecStart=/opt/ha-hub/kokoro/venv/bin/python /usr/local/lib/ha-hub/kokoro_wyoming.py --voice bm_daniel
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sed -i "s/--voice bm_daniel/--voice $voice/" /etc/systemd/system/kokoro-wyoming.service

# Only the Home Assistant VM (by MAC, so IPv4 and IPv6 alike) and the Hub itself
vm_mac=${VM_MAC:-$(virsh domiflist haos | awk '/bridge/ {print $5}')}
cat >/etc/ha-hub/kokoro-fence.nft <<EOF
table inet kokoro_fence
delete table inet kokoro_fence
table inet kokoro_fence {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport 10210 iif lo accept
    tcp dport 10210 ether saddr $vm_mac accept
    tcp dport 10210 reject with tcp reset
  }
}
EOF
cat >/etc/systemd/system/kokoro-fence.service <<'EOF'
[Unit]
Description=Only the Home Assistant VM can reach Kokoro
Before=kokoro-wyoming.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/ha-hub/kokoro-fence.nft
ExecStop=/usr/sbin/nft delete table inet kokoro_fence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kokoro-fence kokoro-wyoming >/dev/null 2>&1
systemctl restart kokoro-fence kokoro-wyoming
echo "kokoro-wyoming: $(systemctl is-active kokoro-wyoming)"
