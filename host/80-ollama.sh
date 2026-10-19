#!/usr/bin/env bash
# Ollama with a small model, as the fallback brain behind Home Assistant's built-in intents.
# Exact phrases still go through Home Assistant's own matcher and stay instant. Whatever it
# doesn't understand comes here.
#
# Pinned to a release that's had a couple of weeks to settle, checked against the sha256 GitHub
# publishes for the asset. The tarball carries CUDA and ROCm libraries this box has no use for,
# so those go straight in the bin.
#
# The model stays loaded (keep alive -1): reloading 1.4 GB on every question costs seconds.
# Qwen3 1.7B is what fits next to the VM in 8 GB. After the RAM upgrade: MODEL=qwen3:4b-instruct
# From the PC: tools/push.sh host/80-ollama.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
version=${OLLAMA_VERSION:-v0.34.4}
model=${MODEL:-qwen3:1.7b}

apt-get install -y -qq --no-install-recommends zstd curl jq

if [ "$(/usr/local/bin/ollama --version 2>/dev/null | grep -o 'v\?[0-9][0-9.]*' | tail -1 | sed 's/^v//')" != "${version#v}" ]; then
  asset=ollama-linux-amd64.tar.zst
  rel=$(curl -fsSL "https://api.github.com/repos/ollama/ollama/releases/tags/$version")
  url=$(jq -r --arg a "$asset" '.assets[] | select(.name == $a) | .browser_download_url' <<<"$rel")
  sha=$(jq -r --arg a "$asset" '.assets[] | select(.name == $a) | .digest' <<<"$rel" | sed 's/^sha256://')
  [ -n "$url" ] && [ -n "$sha" ] && [ "$sha" != null ] || { echo "no $asset or digest for $version"; exit 1; }
  tmp=$(mktemp -d /var/tmp/ollama.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT
  echo "downloading Ollama $version"
  curl -fsSL -o "$tmp/$asset" "$url"
  echo "$sha  $tmp/$asset" | sha256sum -c --quiet
  systemctl stop ollama 2>/dev/null || true
  rm -rf /usr/local/lib/ollama
  tar --zstd -xf "$tmp/$asset" -C /usr/local
  find /usr/local/lib/ollama -mindepth 1 -maxdepth 1 -type d \( -name 'cuda*' -o -name 'rocm*' -o -name 'mlx*' \) -exec rm -rf {} +
fi

id ollama >/dev/null 2>&1 || useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama

# Listens on the LAN because Home Assistant is a separate machine (the VM) on br0. Ollama has no
# auth, so anything on the home network can use it. Fine at home, worth fencing to the VM's IP
# once it has a DHCP reservation.
cat >/etc/systemd/system/ollama.service <<'EOF'
[Unit]
Description=Ollama (local model for Home Assistant)
After=network-online.target
Wants=network-online.target

[Service]
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_KEEP_ALIVE=-1
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_FLASH_ATTENTION=1
Environment=OLLAMA_KV_CACHE_TYPE=q8_0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ollama >/dev/null 2>&1
systemctl restart ollama
for i in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
echo "ollama $(curl -fs http://127.0.0.1:11434/api/version | jq -r .version)"

OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama pull "$model" >/dev/null
OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama list
du -sh /usr/local/lib/ollama /usr/share/ollama/.ollama 2>/dev/null
