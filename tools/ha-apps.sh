#!/usr/bin/env bash
# The Home Assistant side, run from your computer once onboarding is done, the token is in
# ~/.config/ha-hub/token, house.toml is filled in, and the host scripts have run (50-screen.sh
# writes the broker login, 70-voice.sh starts the satellite). In order:
#   1. house.toml gets checked (tools/house.py check). A real problem stops it here
#   2. the scenario tests run on the test bench on the Hub (tools/test.sh, tests/), and nothing
#      deploys if one fails. SKIP_TESTS=1 skips them, for the day the bench itself is the broken part
#   3. tools/setup_ha.py does the rest: the apps (SSH, Mosquitto, Whisper, Piper), the discovered
#      integrations, the TV, the speech engines on the Hub, the rooms, the standard names and the
#      lights from house.toml, ha/config copied into /config (restarting only on a change), the cloud
#      agent's prompt, the voice pipeline, the vacuum's rooms, the doorbell's names, the backups,
#      presence, the starting values, what Jarvis can see, the automations, the calendar, the
#      dashboards, and a restart if the agent's prompt changed
# Safe to rerun, and you will: after adding a device, after changing house.toml, after a pull.
# Extra arguments are setup_ha.py step names, to run just those (tools/setup_ha.py has the list).
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1  # Windows Python reads pipes as cp1252 otherwise, and device names aren't all ASCII

python tools/house.py check

if [ "${SKIP_TESTS:-0}" != 1 ]; then
  echo "scenario tests"
  bash tools/test.sh -q -W ignore::DeprecationWarning -x --show-capture=no || { echo "a scenario failed, nothing deployed"; exit 1; }
fi

python tools/setup_ha.py "$@"
