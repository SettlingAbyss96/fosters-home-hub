#!/usr/bin/env bash
# The scenario tests (tests/), on the test bench on the Hub (host/90-test-env.sh): the real packages
# in Home Assistant 2026.10.0 with a frozen clock. Extra arguments go to pytest, so
#   tools/test.sh -k wake -x
# runs just the wake-up tests and stops at the first failure. tools/ha-apps.sh runs it before every
# deploy and stops if it fails.
set -euo pipefail
cd "$(dirname "$0")/.."
target=${HUB:-$(python tools/house.py get hub.ssh hub@ha-hub.local)}
# a run orphaned by a dropped connection would otherwise still be going
ssh "$target" 'pkill -f "[h]a-test/venv/bin/python -m pytest" || true'
tar -c ha/config tests tools/setup_ha.py tools/house.py | ssh "$target" 'rm -rf ~/ha-test/work && mkdir -p ~/ha-test/work && tar -x -C ~/ha-test/work'
args=$(printf '%q ' "$@")
ssh "$target" "cd ~/ha-test/work/tests && ~/ha-test/venv/bin/python -m pytest -q -p no:cacheprovider --timeout 180 $args"
