#!/usr/bin/env bash
# Home Assistant OS as a KVM guest on br0, so it gets its own IP on the LAN.
# Pulls the latest haos_ova qcow2 from the official GitHub release and checks it against the
# sha256 GitHub publishes for the asset. Does nothing if the VM already exists.
# Sizing is for the Hub's stock 8 GB: 3 GB in use out of 4, the rest kept back by the balloon so it
# can go back without a reboot (virsh setmem haos 4G --live). With all 4 the guest fills 2 GB of it
# with its own disk cache while the Hub pushes Kokoro and Parakeet out to swap, and Jarvis's first
# sentence after a quiet spell takes more than twice as long to start. Rerunning this on an
# existing VM sets just that. With 16 GB in it: HAOS_MEM=8192 HAOS_MAX=8192.
# From the PC: ssh hub@ha-hub.local 'sudo bash -s' < host/30-haos-vm.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

name=haos
img=/var/lib/libvirt/images/$name.qcow2
mem=${HAOS_MEM:-3072}
max=${HAOS_MAX:-4096}
cpus=${HAOS_CPUS:-3}
disk=${HAOS_DISK:-64G}

if virsh -c qemu:///system dominfo "$name" >/dev/null 2>&1; then
  virsh -c qemu:///system setmaxmem "$name" "${max}M" --config >/dev/null
  virsh -c qemu:///system setmem "$name" "${mem}M" --config >/dev/null
  virsh -c qemu:///system setmem "$name" "${mem}M" --live >/dev/null 2>&1 ||
    echo "$name gets ${mem} MiB at its next restart, past the most it booted with"
  echo "$name already exists, left alone apart from its memory: $(virsh -c qemu:///system dommemstat "$name" | awk '/^actual/ {print $2 / 1024 " MiB"}')"
  exit 0
fi

rel=$(curl -fsSL https://api.github.com/repos/home-assistant/operating-system/releases/latest)
ver=$(jq -r .tag_name <<<"$rel")
asset="haos_ova-$ver.qcow2.xz"
url=$(jq -r --arg a "$asset" '.assets[] | select(.name == $a) | .browser_download_url' <<<"$rel")
sha=$(jq -r --arg a "$asset" '.assets[] | select(.name == $a) | .digest' <<<"$rel" | sed 's/^sha256://')
[ -n "$url" ] && [ -n "$sha" ] || { echo "couldn't find $asset or its digest"; exit 1; }

tmp=$(mktemp -d /var/tmp/haos.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
echo "downloading HAOS $ver"
curl -fsSL -o "$tmp/$asset" "$url"
echo "$sha  $tmp/$asset" | sha256sum -c --quiet
xz -d "$tmp/$asset"
# HAOS grows its data partition to fill the disk on first boot, and qcow2 stays sparse
qemu-img resize -q "$tmp/haos_ova-$ver.qcow2" "$disk"
mv "$tmp/haos_ova-$ver.qcow2" "$img"

# HAOS isn't signed for Secure Boot, so plain UEFI. The guest agent channel lets the host shut
# it down cleanly. cache=none and discard keep a power cut from eating writes and pass TRIM through.
virt-install --connect qemu:///system \
  --name "$name" --description "Home Assistant OS $ver" \
  --osinfo generic \
  --boot uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=no \
  --cpu host-passthrough --vcpus "$cpus" --memory memory="$max",currentMemory="$mem" \
  --disk path="$img",bus=virtio,cache=none,discard=unmap \
  --network bridge=br0,model=virtio \
  --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
  --graphics none --console pty,target.type=serial \
  --import --noautoconsole --autostart

# On host shutdown, ask the VM to shut down properly instead of freezing it to disk
sed -i -E 's/^#?ON_BOOT=.*/ON_BOOT=ignore/; s/^#?ON_SHUTDOWN=.*/ON_SHUTDOWN=shutdown/; s/^#?SHUTDOWN_TIMEOUT=.*/SHUTDOWN_TIMEOUT=180/' \
  /etc/default/libvirt-guests
systemctl enable --now libvirt-guests >/dev/null 2>&1

virsh -c qemu:///system domiflist "$name"
