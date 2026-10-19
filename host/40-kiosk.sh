#!/usr/bin/env bash
# The touchscreen: labwc (a small Wayland compositor) running Chromium maximized in app mode on
# the Home Assistant dashboard, started on tty1 at boot as user hub, with Squeekboard (the Linux
# phones' touch keyboard) sliding up whenever a text field gets focus.
# Log in once on the screen and Chromium keeps the session.
#
# This used to be cage, which runs one app and nothing else. Lovely and minimal, but it has no
# layer-shell or input-method support, so a keyboard has nowhere to draw and no way to know a text
# field was tapped. labwc has both.
#
# Settings live in /etc/default/ha-kiosk, and the script won't overwrite that file on a rerun.
# From the PC: tools/push.sh host/40-kiosk.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

user=hub
home=$(getent passwd "$user" | cut -d: -f6)

# librsvg2-common and adwaita-icon-theme are for Squeekboard: its key icons are SVGs, and without
# an SVG loader shift, enter and the globe key just say "icon"
apt-get install -y -qq --no-install-recommends \
  labwc squeekboard librsvg2-common adwaita-icon-theme chromium wlr-randr grim libnss-mdns \
  fonts-noto-color-emoji intel-media-va-driver mesa-vulkan-drivers libgl1-mesa-dri \
  dbus-user-session jq python3-websockets

if [ ! -f /etc/default/ha-kiosk ]; then
  cat >/etc/default/ha-kiosk <<'EOF'
# Read by /usr/local/bin/ha-kiosk. Restart with: sudo systemctl restart ha-kiosk
HA_URL=http://homeassistant.local
# The dashboard the screen opens on, from ha/dashboards/ (the rooms page of home-hub)
KIOSK_PATH=/home-hub/home
# 190 PPI panel, so 1.0 is tiny. 1.5 makes the dashboard 1280 x 720 CSS pixels
KIOSK_SCALE=1.5
EOF
fi
# older installs predate KIOSK_PATH and opened on Home Assistant's own overview
grep -q '^KIOSK_PATH=' /etc/default/ha-kiosk ||
  printf '# The dashboard the screen opens on, from ha/dashboards/ (the rooms page of home-hub)\nKIOSK_PATH=/home-hub/home\n' >>/etc/default/ha-kiosk

# Every window maximized with no decorations at all. Maximized and not fullscreen on purpose:
# labwc draws a fullscreen window over the layer the keyboard lives on, so in Chromium's --kiosk
# mode the keyboard pops up behind the page. Maximized, the page shrinks to make room instead.
install -d -o "$user" -g "$user" "$home/.config/labwc"
cat >"$home/.config/labwc/rc.xml" <<'EOF'
<?xml version="1.0"?>
<labwc_config>
  <core>
    <decoration>server</decoration>
    <gap>0</gap>
  </core>
  <theme>
    <cornerRadius>0</cornerRadius>
  </theme>
  <windowRules>
    <windowRule identifier="*" serverDecoration="no">
      <action name="Maximize"/>
    </windowRule>
  </windowRules>
</labwc_config>
EOF
chown "$user:$user" "$home/.config/labwc/rc.xml"

cat >/usr/local/bin/ha-kiosk <<'EOF'
#!/usr/bin/env bash
# Runs inside labwc. Waits for Home Assistant, starts the keyboard, then hands the screen to
# Chromium. labwc runs this with -S, so when Chromium exits the whole session ends and systemd
# starts a fresh one.
set -u
. /etc/default/ha-kiosk
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus

# After a power cut the VM needs a minute or two. Chromium's error page doesn't retry on its own,
# so hold a black screen until Home Assistant answers instead.
until curl -sf -o /dev/null --max-time 3 "$HA_URL/manifest.json"; do sleep 2; done

# Scale the panel itself. Chromium's --force-device-scale-factor on Wayland draws into a quarter
# of the screen, which is a fun way to find out it's broken.
out=$(wlr-randr | awk 'NR==1 {print $1}')
wlr-randr --output "$out" --scale "$KIOSK_SCALE"

# Squeekboard only pops up by itself when this is on
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled true
squeekboard >/dev/null 2>&1 &

profile="$HOME/.config/ha-kiosk"
prefs="$profile/Default/Preferences"
# custom_chrome_frame off means Chromium leaves the title bar to the compositor, which has been told
# to draw none. Seeded on a fresh profile so even the first start has no title bar
if [ -f "$prefs" ]; then
  jq '.browser.custom_chrome_frame = false' "$prefs" >"$prefs.tmp" && mv "$prefs.tmp" "$prefs"
else
  mkdir -p "$profile/Default"
  echo '{"browser":{"custom_chrome_frame":false}}' >"$prefs"
fi
# The session gets killed rather than closed, so tell Chromium it exited cleanly or it nags to
# restore tabs
sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$prefs"

# Hide Home Assistant's sidebar once Chromium is up (see ha-kiosk-page)
(sleep 15; /usr/local/bin/ha-kiosk-page) >/dev/null 2>&1 &

# App mode (no tabs or address bar), maximized rather than --kiosk fullscreen, see rc.xml.
# --enable-wayland-ime with text-input v3 is what lets a focused text field ask for the keyboard.
# The debugging port is what ha-kiosk-page talks to. Chromium binds it to 127.0.0.1 only, and
# anything already on the Hub could do worse than drive a browser.
# --disable-gpu: Chromium draws in software and hands labwc plain shared-memory buffers. With the
# GPU on, the screen froze now and then (labwc stopped presenting frames with "Atomic commit failed:
# Device or resource busy" on DP-1), most reliably a few minutes after opening a sensor's history
# dialog, whose chart redraws constantly. A dashboard is light work for this CPU
exec chromium \
  --app="$HA_URL${KIOSK_PATH:-}" --start-maximized --ozone-platform=wayland \
  --disable-gpu \
  --enable-wayland-ime --wayland-text-input-version=3 \
  --remote-debugging-port=9222 \
  --user-data-dir="$profile" \
  --noerrdialogs --disable-infobars --no-first-run --no-default-browser-check \
  --disable-features=Translate,TranslateUI \
  --disable-pinch --overscroll-history-navigation=0 \
  --password-store=basic \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000
EOF
chmod 755 /usr/local/bin/ha-kiosk

# Home Assistant's sidebar eats 255 of the screen's 1280 pixels, which leaves the dashboard two
# columns instead of three. Hiding it is a per-browser setting (Profile, "Always hide the
# sidebar", which is just dockedSidebar in local storage), so there's nothing on the server side
# to set. This sets it through Chromium's debugging port and reloads, and does nothing if it's
# already set. The menu button still opens the sidebar when it's needed.
#   ha-kiosk-page            hide the sidebar
#   ha-kiosk-page /some/path also open that page
cat >/usr/local/bin/ha-kiosk-page <<'EOF'
#!/usr/bin/env python3
import asyncio, json, sys, urllib.request
import websockets

JS = """(() => {
  const want = JSON.stringify("always_hidden");
  const path = %s;
  let reload = false;
  if (localStorage.getItem("dockedSidebar") !== want) { localStorage.setItem("dockedSidebar", want); reload = true; }
  if (path && (location.pathname !== path || location.search)) { location.href = path; return "navigated"; }
  if (reload) { location.reload(); return "sidebar hidden"; }
  return "already set";
})()"""

async def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    for _ in range(30):
        try:
            pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3))
            page = next(p for p in pages if p.get("type") == "page" and "homeassistant" in p.get("url", ""))
            break
        except Exception:  # Chromium still starting, or still on the black wait screen
            await asyncio.sleep(2)
    else:
        sys.exit("no Home Assistant page in the kiosk")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": JS % json.dumps(path), "returnByValue": True}}))
        print(json.loads(await ws.recv()).get("result", {}).get("result", {}).get("value"))

asyncio.run(main())
EOF
chmod 755 /usr/local/bin/ha-kiosk-page

# The USB audio device's consumer-control HID says it's a pointer, so the compositor draws a cursor
# in the middle of the screen that touch never moves. Libinput ignores it. Its raw evdev node still
# works for anything that wants the buttons later.
cat >/etc/udev/rules.d/90-hub-no-fake-pointer.rules <<'EOF'
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Generic USB Audio Consumer Control", ENV{LIBINPUT_IGNORE_DEVICE}="1"
EOF
udevadm control --reload
udevadm trigger --subsystem-match=input --action=change

# PAM stack for the session the service opens, so hub gets a real logind seat session on tty1
cat >/etc/pam.d/ha-kiosk <<'EOF'
auth     required pam_unix.so nullok
account  required pam_unix.so
session  required pam_unix.so
session  required pam_systemd.so
EOF

cat >/etc/systemd/system/ha-kiosk.service <<EOF
[Unit]
Description=Home Assistant kiosk on the touchscreen
After=systemd-user-sessions.service dbus.socket systemd-logind.service network-online.target
Wants=dbus.socket systemd-logind.service network-online.target
Conflicts=getty@tty1.service
After=getty@tty1.service
ConditionPathExists=/dev/tty1

[Service]
User=$user
PAMName=ha-kiosk
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
StandardOutput=journal
StandardError=journal
UtmpIdentifier=tty1
UtmpMode=user
# No direct scanout: wlroots otherwise puts a window that fills the screen straight onto the
# panel's plane, skipping its own compositing, which is the path that stalled here (see --disable-gpu)
Environment=WLR_SCENE_DISABLE_DIRECT_SCANOUT=1
# -S: run the kiosk script as the session, and end the compositor when it exits
ExecStart=/usr/bin/labwc -S /usr/local/bin/ha-kiosk
Restart=always
TimeoutStopSec=10
RestartSec=3

[Install]
WantedBy=graphical.target
EOF

# A watchdog. labwc has stopped answering on this box before, after a few hours: the screen froze
# with everything still "running", nothing in any log, no GPU hang in dmesg, and even grim hung
# waiting on it. So once a minute, ask the compositor something trivial, and if it can't answer
# within 10 s twice in a row, restart the kiosk
cat >/usr/local/bin/ha-kiosk-watchdog <<'EOF'
#!/bin/sh
state=/run/ha-kiosk-watchdog
systemctl is-active --quiet ha-kiosk || exit 0
u=$(ps -o user= -C labwc | head -1)
[ -n "$u" ] || exit 0
id=$(id -u "$u")
sock=$(ls /run/user/$id 2>/dev/null | grep -m1 '^wayland-[0-9]$')
[ -n "$sock" ] || exit 0
# a tiny screenshot, because one kind of freeze still answers wlr-randr while drawing nothing
if timeout 10 runuser -u "$u" -- env XDG_RUNTIME_DIR=/run/user/$id WAYLAND_DISPLAY=$sock grim -s 0.1 - >/dev/null 2>&1; then
  rm -f "$state"
elif [ -f "$state" ]; then
  echo "compositor not answering twice in a row, restarting the kiosk"
  rm -f "$state"
  systemctl restart ha-kiosk
else
  touch "$state"
  echo "compositor didn't answer, checking again in a minute"
fi
EOF
chmod 755 /usr/local/bin/ha-kiosk-watchdog
cat >/etc/systemd/system/ha-kiosk-watchdog.service <<'EOF'
[Unit]
Description=Restart the kiosk if its compositor stops answering

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ha-kiosk-watchdog
EOF
cat >/etc/systemd/system/ha-kiosk-watchdog.timer <<'EOF'
[Unit]
Description=Check the kiosk's compositor every minute

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl set-default graphical.target >/dev/null
systemctl enable ha-kiosk >/dev/null 2>&1
systemctl enable --now ha-kiosk-watchdog.timer >/dev/null 2>&1
systemctl restart ha-kiosk
echo "ha-kiosk: $(systemctl is-active ha-kiosk), watchdog: $(systemctl is-active ha-kiosk-watchdog.timer)"
