#!/usr/bin/env bash
# The community pieces Home Assistant doesn't ship, pinned by version and sha256, no HACS. Which
# ones get installed is extras.install in house.toml:
#   - mushroom: Mushroom 5.2.3, the cards the dashboard is built from. Every house needs this one
#   - moonraker: Moonraker 1.13.4 (custom integration) for a Klipper printer, added at
#     klipper.moonraker as "Klipper" with no API key (Moonraker trusts the LAN by default)
#   - bambu: Bambu Lab 2.2.26 (greghesp/ha-bambulab, MIT). Local over the printer's own MQTT, FTP
#     and camera ports with the access code from its screen, which you type in when you add it;
#     Bambu's cloud only if the cloud option is picked at setup. Its one Python requirement,
#     beautifulsoup4, Home Assistant installs itself
#   - oura: Oura Ring 2.10.3 (louispires, MIT), the ring straight from Oura's API instead of waiting
#     for its app to sync into the phone's health app. Talks to api.ouraring.com and nothing else,
#     no Python requirements. Needs your own Oura developer app (redirect URI
#     https://my.home-assistant.io/redirect/oauth), whose client ID and secret you enter under
#     Application credentials. 2.10.3 for its fix to setup timing out on a restart
#   - hass_agent: HASS.Agent integration 2.1.3 (hass-agent, MIT), the Home Assistant half of
#     HASS.Agent on a Windows computer: the computer as a media player (TTS and music through its
#     speakers) and a notify target. Sensors and commands come over MQTT without it, this is the
#     part that needs code. Talks to MQTT and the computer's own local API (port 5115) and nothing else
#   - vacuum_map: Xiaomi Vacuum Map Card 2.4.1, an interactive map for a Roborock, as a dashboard
#     resource, plus Roborock Custom Map 0.1.6, which gives the card a map image with calibration
#     points and room outlines (the core Roborock integration's own map image has neither, so the
#     card can show it but not click on it). It rides on the core integration's data, no login
#   - piper_jarvis: the Jarvis voice for Piper (jgkawell/jarvis on Hugging Face, MIT), medium and
#     high, into /share/piper where the Piper app looks for custom voices. Only the fallback, when
#     Kokoro (host/74-kokoro.sh) isn't there
#   - audi: Audi Connect 2.5.1 (audiconnect/audi_connect_ha), the car: plugged in, charging, the
#     battery and when it'll be done, for the idle-fee reminders (packages/car.yaml). You sign in
#     with the myAudi login under Devices & Services and pick your region. Talks to Audi and
#     Volkswagen Group hosts only, one Python requirement, beautifulsoup4, the same one Bambu has.
#     Read before pinning: it logs the session token at debug level and nothing at the normal
#     levels. Audi has been refusing European logins to it since October 2026; US ones go another way
# Updating one means a new version and a new sha256 below, nothing else. Run after ha-apps.sh.
# Home Assistant restarts only when a file in /config actually changed.
set -euo pipefail
cd "$(dirname "$0")/.."
ha() { python tools/ha.py "$@"; }
ha_host=${HA_HOST:-$(python tools/house.py get home_assistant.host homeassistant.local)}
ssh_ha() { ssh -4 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "root@$ha_host" "$@"; }
trap 'rm -rf .tmp-extras' EXIT
want=" $(python tools/house.py get extras.install mushroom | tr '\n' ' ') "
wants() { case "$want" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

moonraker_ver=1.13.4
moonraker_sha=f72f7ad4b2299a991b1ba11c1d7bf600d4713686f3a6bbcbf2afd21b32b08907
card_ver=2.4.1
card_sha=6eb544c670480607c75d82321bb5d1932c781098c1f34391084ecefcac23d445
rcm_ver=0.1.6
rcm_sha=709f8f1eaec128f9465d98b3774faac4cee4d0b2117f7fa8f373be639e19d80f
mushroom_ver=5.2.3
mushroom_sha=631668268e474d5357e0f17f161322499ea5c93a910431477e112653d7aa456b
oura_ver=2.10.3
oura_sha=b1146d1eb4549dc681da4bb9f42d4e0d878090fa30f704a01ee0b131eb5c7a90
hassagent_ver=2.1.3
hassagent_sha=b9e829645c249449d1d45a2dd2621b80ec120f2a0c1d0989fcbf67b0432b404c
bambu_ver=2.2.26
bambu_sha=7d2d8c7d3ba5faf08a6ccc6bc870bda4cb8ce3fbf362d92119f3185dca802626
audi_ver=2.5.1
audi_sha=903bd45ac05dbb711dbaa5b2a25afcefabc732189a008d731da9e59c0ee388ef

fetch() {  # fetch URL FILE SHA256
  curl -fsSL -m 120 -o "$2" "$1"
  echo "$3  $2" | sha256sum -c --quiet - || { echo "checksum mismatch on $1"; exit 1; }
}

rm -rf .tmp-extras && mkdir -p .tmp-extras/config/custom_components .tmp-extras/config/www
if wants moonraker; then
  fetch "https://codeload.github.com/marcolivierarsenault/moonraker-home-assistant/tar.gz/refs/tags/$moonraker_ver" \
    .tmp-extras/moonraker.tar.gz "$moonraker_sha"
  tar -xzf .tmp-extras/moonraker.tar.gz -C .tmp-extras --strip-components=2 \
    "moonraker-home-assistant-$moonraker_ver/custom_components/moonraker"
  mv .tmp-extras/moonraker .tmp-extras/config/custom_components/
fi
if wants vacuum_map; then
  fetch "https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card/releases/download/v$card_ver/xiaomi-vacuum-map-card.js" \
    .tmp-extras/config/www/xiaomi-vacuum-map-card.js "$card_sha"
  fetch "https://github.com/Python-roborock/RoborockCustomMap/releases/download/$rcm_ver/roborock_custom_map.zip" \
    .tmp-extras/rcm.zip "$rcm_sha"
  python -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
    .tmp-extras/rcm.zip .tmp-extras/config/custom_components/roborock_custom_map
fi
if wants mushroom; then
  fetch "https://github.com/piitaya/lovelace-mushroom/releases/download/v$mushroom_ver/mushroom.js" \
    .tmp-extras/config/www/mushroom.js "$mushroom_sha"
fi
if wants oura; then
  fetch "https://codeload.github.com/louispires/Oura-Home-Assistant-Integration/tar.gz/refs/tags/v$oura_ver" \
    .tmp-extras/oura.tar.gz "$oura_sha"
  tar -xzf .tmp-extras/oura.tar.gz -C .tmp-extras --strip-components=2 \
    "Oura-Home-Assistant-Integration-$oura_ver/custom_components/oura"
  mv .tmp-extras/oura .tmp-extras/config/custom_components/
fi
if wants hass_agent; then
  fetch "https://codeload.github.com/hass-agent/HASS.Agent-Integration/tar.gz/refs/tags/$hassagent_ver" \
    .tmp-extras/hassagent.tar.gz "$hassagent_sha"
  tar -xzf .tmp-extras/hassagent.tar.gz -C .tmp-extras --strip-components=2 \
    "HASS.Agent-Integration-$hassagent_ver/custom_components/hass_agent"
  mv .tmp-extras/hass_agent .tmp-extras/config/custom_components/
fi
if wants bambu; then
  fetch "https://codeload.github.com/greghesp/ha-bambulab/tar.gz/refs/tags/v$bambu_ver" .tmp-extras/bambu.tar.gz "$bambu_sha"
  tar -xzf .tmp-extras/bambu.tar.gz -C .tmp-extras --strip-components=2 "ha-bambulab-$bambu_ver/custom_components/bambu_lab"
  mv .tmp-extras/bambu_lab .tmp-extras/config/custom_components/
fi
if wants audi; then
  fetch "https://codeload.github.com/audiconnect/audi_connect_ha/tar.gz/refs/tags/v$audi_ver" .tmp-extras/audi.tar.gz "$audi_sha"
  tar -xzf .tmp-extras/audi.tar.gz -C .tmp-extras --strip-components=2 "audi_connect_ha-$audi_ver/custom_components/audiconnect"
  mv .tmp-extras/audiconnect .tmp-extras/config/custom_components/
fi

# same copy-if-different as ha/config in tools/setup_ha.py, so a rerun doesn't restart anything. Only a
# new integration needs a restart, a card in www/ is just a file the browser fetches
changed=$(tar -C .tmp-extras/config -c . | ssh_ha '
  rm -rf /tmp/ha-hub-extras && mkdir -p /tmp/ha-hub-extras && tar -x -C /tmp/ha-hub-extras
  cd /tmp/ha-hub-extras && changed=0
  for f in $(find . -type f); do
    cmp -s "$f" "/config/$f" && continue
    mkdir -p "$(dirname "/config/$f")"; cp "$f" "/config/$f"
    case "$f" in ./custom_components/*) changed=1 ;; esac
  done
  echo $changed')
if [ "$changed" = 1 ]; then
  ssh_ha 'ha core check >/dev/null && ha core restart >/dev/null' && echo "extras changed, Home Assistant restarted"
  sleep 20
  for i in $(seq 1 40); do ha get api/ >/dev/null 2>&1 && break; sleep 5; done
else
  echo "extras unchanged"
fi

# The Jarvis voice for Piper. A fan-made model that sounds like the films' Jarvis. High takes 2.7 s
# a reply on the Hub against 0.8 s for medium, and sounds a lot better for it; medium stays as the
# quick fallback. Downloaded inside Home Assistant rather than through this computer, because it's
# 180 MB. The model files are pinned by commit and sha256 like everything else in here
if wants piper_jarvis; then
  voice_rev=37f8763122312665f091d1fc760abaf1f79b02cc
  voices_changed=$(ssh_ha "set -e; mkdir -p /share/piper; cd /share/piper; changed=0
    for pair in medium:3f6534bd4050931b4c7d16ef777bafa2d90eb1e7baa8af9358623ffe609506da \
                high:9791877d9c099fabbf30be2825e011451c39b3431e21e81e866f5b6507e72993; do
      q=\${pair%%:*}; sha=\${pair#*:}
      echo \"\$sha  jarvis-\$q.onnx\" | sha256sum -c -s - 2>/dev/null && continue
      base=https://huggingface.co/jgkawell/jarvis/resolve/$voice_rev/en/en_GB/jarvis/\$q
      curl -fsSL -o jarvis-\$q.onnx.tmp \"\$base/jarvis-\$q.onnx\"
      echo \"\$sha  jarvis-\$q.onnx.tmp\" | sha256sum -c -s - || { rm -f jarvis-\$q.onnx.tmp; exit 1; }
      mv jarvis-\$q.onnx.tmp jarvis-\$q.onnx
      curl -fsSL -o jarvis-\$q.onnx.json \"\$base/jarvis-\$q.onnx.json\"
      changed=1
    done
    echo \$changed")
  if [ "$voices_changed" = 1 ]; then
    ha sup post addons/core_piper/restart >/dev/null && echo "Jarvis voice installed, Piper restarted"
  fi
fi

# the cards as dashboard resources, with the version in the URL so browsers drop the old one
resources=""
wants mushroom && resources="$resources mushroom.js?v=$mushroom_ver"
wants vacuum_map && resources="$resources xiaomi-vacuum-map-card.js?v=$card_ver"
for res in $resources; do
  existing=$(ha ws '{"type":"lovelace/resources"}' | python -c "
import json, sys
print(next((r['id'] for r in json.load(sys.stdin) if '/${res%%\?*}' in r['url']), ''))")
  if [ -z "$existing" ]; then
    ha ws "{\"type\":\"lovelace/resources/create\",\"res_type\":\"module\",\"url\":\"/local/$res\"}" >/dev/null
  else
    ha ws "{\"type\":\"lovelace/resources/update\",\"resource_id\":\"$existing\",\"res_type\":\"module\",\"url\":\"/local/$res\"}" >/dev/null
  fi
done

# The Klipper printer, named Klipper so its entities are sensor.klipper_... (docs/devices.md)
moonraker=$(python tools/house.py get klipper.moonraker "")
if wants moonraker && [ -n "$moonraker" ] &&
   [ -z "$(ha ws '{"type":"config_entries/get","domain":"moonraker"}' | python -c "import json,sys; print(len(json.load(sys.stdin)) or '')")" ]; then
  body=$(MOONRAKER="$moonraker" python -c "
import json, os, urllib.parse
u = urllib.parse.urlparse(os.environ['MOONRAKER'] if '://' in os.environ['MOONRAKER'] else 'http://' + os.environ['MOONRAKER'])
print(json.dumps({'url': u.hostname, 'port': str(u.port or 7125), 'tls': u.scheme == 'https', 'api_key': '', 'printer_name': 'Klipper'}))")
  fid=$(ha post api/config/config_entries/flow '{"handler":"moonraker"}' | python -c "import json,sys; print(json.load(sys.stdin)['flow_id'])")
  ha post "api/config/config_entries/flow/$fid" "$body" \
    | python -c "import json,sys; r=json.load(sys.stdin); print('Klipper:', r.get('type'), r.get('errors') or '')"
fi
# Voice gets the handful of things worth asking about, not all eighty. Every exposed entity makes
# the agent's prompt longer
python tools/ha.py expose on sensor.klipper_current_print_state sensor.klipper_progress sensor.klipper_print_time_left \
  sensor.klipper_extruder_temperature sensor.klipper_bed_temperature

# Roborock Custom Map, once the core Roborock integration is in (it needs it loaded first)
if wants vacuum_map &&
   [ -n "$(ha ws '{"type":"config_entries/get","domain":"roborock"}' | python -c "import json,sys; print(len(json.load(sys.stdin)) or '')")" ] &&
   [ -z "$(ha ws '{"type":"config_entries/get","domain":"roborock_custom_map"}' | python -c "import json,sys; print(len(json.load(sys.stdin)) or '')")" ]; then
  ha post api/config/config_entries/flow '{"handler":"roborock_custom_map"}' \
    | python -c "import json,sys; print('Roborock Custom Map:', json.load(sys.stdin).get('type'))"
fi
