#!/usr/bin/env bash
# KVM and libvirt for the Home Assistant OS VM. HAOS only boots UEFI, hence ovmf.
# From the PC: ssh hub@ha-hub.local 'sudo bash -s' < host/10-virt.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

[ -e /dev/kvm ] || { echo "no /dev/kvm, turn on VT-x in the BIOS"; exit 1; }

apt-get install -y -qq --no-install-recommends \
  qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst \
  ovmf dnsmasq-base xz-utils

usermod -aG libvirt,kvm "${SUDO_USER:-hub}"
systemctl is-active --quiet libvirtd && echo "libvirtd running"
