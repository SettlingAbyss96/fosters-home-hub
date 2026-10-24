#!/usr/bin/env bash
# Builds the TV keeper (tv/keeper) on the Hub and brings the app back to tv/keeper/build/keeper.apk,
# which isn't kept in the repo. Then `python tools/tv.py install-keeper` puts it on the TV.
# The Hub needs host/79-android.sh first. The Hub is hub.ssh in house.toml, and HUB overrides it
set -euo pipefail
cd "$(dirname "$0")/.."
target=${HUB:-$(python tools/house.py get hub.ssh hub@ha-hub.local)}
tar -c --exclude=keeper/build -C tv keeper | ssh "$target" 'rm -rf ~/tv-keeper && mkdir -p ~/tv-keeper && tar -x -C ~/tv-keeper && bash ~/tv-keeper/keeper/build.sh'
mkdir -p tv/keeper/build
scp -q "$target:tv-keeper/keeper/build/keeper.apk" tv/keeper/build/keeper.apk
echo "tv/keeper/build/keeper.apk"
