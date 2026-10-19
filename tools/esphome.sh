#!/usr/bin/env bash
# The ESP32 sensor nodes (esphome/), checked, built and updated on the Hub (host/78-esphome.sh):
#   tools/esphome.sh config bedroom-sense    check the YAML, nothing built
#   tools/esphome.sh compile bedroom-sense   build it
#   tools/esphome.sh run bedroom-sense       build it and update the node over Wi-Fi
#   tools/esphome.sh logs bedroom-sense      the node's log, live
#   tools/esphome.sh bin bedroom-sense       build it and copy the image to esphome/build/, for
#                                            the first flash over USB at https://web.esphome.io
# Without a node name it does every node. The Hub is hub.ssh in house.toml, HUB overrides it.
set -euo pipefail
cd "$(dirname "$0")/.."
target=${HUB:-$(python tools/house.py get hub.ssh hub@ha-hub.local)}
cmd=${1:?"config, compile, run, logs or bin"}
shift
nodes=${*:-$(cd esphome && ls ./*.yaml | sed 's|^\./||; s|\.yaml$||')}
dir=/opt/ha-hub/esphome

# the configs go over, the secrets stay where they are: a link in each folder that needs them
tar -c --exclude esphome/build --exclude esphome/.esphome esphome | ssh "$target" "
  set -e
  cd $dir/work && find . -maxdepth 2 -name '*.yaml' ! -name secrets.yaml -delete
  tar -x --strip-components=1 -C $dir/work
  ln -sf $dir/secrets.yaml $dir/work/secrets.yaml
  ln -sf $dir/secrets.yaml $dir/work/common/secrets.yaml"

for node in $nodes; do
  echo "== $node"
  case $cmd in
    bin)
      ssh "$target" "cd $dir/work && $dir/venv/bin/esphome compile $node.yaml"
      mkdir -p esphome/build
      img=$(ssh "$target" "find $dir/work/.esphome/build/$node -name firmware.factory.bin | head -1")
      scp -q "$target:$img" "esphome/build/$node.factory.bin"
      echo "esphome/build/$node.factory.bin"
      ;;
    logs) ssh -t "$target" "cd $dir/work && $dir/venv/bin/esphome logs $node.yaml" ;;
    *) ssh "$target" "cd $dir/work && $dir/venv/bin/esphome $cmd $node.yaml" ;;
  esac
done
