#!/usr/bin/env python3
"""The Fire TV, through the ADB connection Home Assistant already has to it (androidtv, from
fire_tv in house.toml), so nothing new has to be allowed on the TV. Standard library only, like ha.py.

  python tools/tv.py run 'getprop ro.product.model'   one shell command, prints the answer
  python tools/tv.py apply     tv/debloat.txt (yours, copied from tv/debloat.example.txt and made to
                               fit your TV): its packages off, its settings set, its private DNS on.
                               The state from before goes in tv/before.txt the first time, and never
                               gets overwritten (a setting added to the list later gets its old value
                               added then)
  python tools/tv.py check     what's drifted from the list (a Fire OS update brings packages back),
                               exit 1 if anything has
  python tools/tv.py restore   back to tv/before.txt: what was on goes back on, the settings and the
                               DNS go back, and the keeper comes off
  python tools/tv.py install-keeper   the keeper app (tv/keeper, built by tools/tv-keeper.sh) onto the
                               TV, with the one permission it needs, and started once

Home Assistant reads the TV every few seconds for sensor.tv_status, and each command's answer lands in
the same attribute, so every command here ends with a marker and gets read back straight away, again
if the house's own poll got there first.
"""
import base64
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _house(key, default):
    """A value from house.toml, the same way the shell scripts read it"""
    import subprocess
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "house.py"), "get", key, default],
                         capture_output=True, text=True)
    return out.stdout.strip() or default


URL = os.environ.get("HA_URL") or _house("home_assistant.url", "http://homeassistant.local")
URL = URL.rstrip("/")
TV = "media_player.fire_tv"
LIST = ROOT / "tv" / "debloat.txt"
BEFORE = ROOT / "tv" / "before.txt"
KEEPER_APK = ROOT / "tv" / "keeper" / "build" / "keeper.apk"
KEEPER = "home.hub.tvkeeper"


def token():
    t = os.environ.get("HA_TOKEN")
    return t or (pathlib.Path.home() / ".config" / "ha-hub" / "token").read_text().strip()


def post(path, body):
    req = urllib.request.Request(f"{URL}/{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode()


def run(cmd):
    mark = "END" + uuid.uuid4().hex[:8]
    for _ in range(8):
        post("api/services/androidtv/adb_command", {"entity_id": TV, "command": f"{cmd}; echo {mark}"})
        out = post("api/template", {"template": f"{{{{ state_attr('{TV}', 'adb_response') }}}}"})
        if mark in out:
            return out.split(mark)[0].strip()
        time.sleep(0.3)
    raise SystemExit(f"no answer from the TV to: {cmd}")


def read_list():
    """The packages to switch off, the settings ("setting global <name> <value>") and the private DNS"""
    if not LIST.exists():
        raise SystemExit("no tv/debloat.txt: copy tv/debloat.example.txt there and make it fit your TV first")
    packages, settings, dns = [], {}, None
    for line in LIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line.startswith("private-dns "):
            dns = line.split(None, 1)[1]
        elif line.startswith("setting "):
            _, table, name, value = line.split(None, 3)
            settings[(table, name)] = value
        elif line:
            packages.append(line)
    return packages, settings, dns


def setting_now(table, name):
    return run(f"settings get {table} {name}").strip()


def states():
    """Every package on the TV: 'enabled' or 'disabled' (for user 0)"""
    every = {l.replace("package:", "").strip() for l in run("pm list packages").splitlines() if l.startswith("package:")}
    off = {l.replace("package:", "").strip() for l in run("pm list packages -d").splitlines() if l.startswith("package:")}
    return {p: ("disabled" if p in off else "enabled") for p in every}


def dns_now():
    mode, spec = run("settings get global private_dns_mode; settings get global private_dns_specifier").splitlines()[:2]
    return mode.strip(), spec.strip()


def record(packages, settings):
    if BEFORE.exists():
        text = BEFORE.read_text(encoding="utf-8")
        new = [f"setting {t} {n} {setting_now(t, n)}" for t, n in settings if f"setting {t} {n} " not in text]
        if new:
            BEFORE.write_text(text + "\n".join(new) + "\n", encoding="utf-8", newline="\n")
        return
    now = states()
    mode, spec = dns_now()
    lines = ["# What the TV had before tools/tv.py apply first ran, for restore. Written once, never",
             f"# overwritten. {run('getprop ro.product.model')}, {run('getprop ro.build.version.name')}",
             f"private-dns-mode {mode}", f"private-dns-specifier {spec}"]
    lines += [f"{p} {now.get(p, 'missing')}" for p in packages]
    lines += [f"setting {t} {n} {setting_now(t, n)}" for t, n in settings]
    BEFORE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"recorded the state from before in {BEFORE.relative_to(ROOT)}")


def apply():
    packages, settings, dns = read_list()
    record(packages, settings)
    now = states()
    for p in packages:
        if now.get(p) != "enabled":
            print(f"  {p}: {now.get(p, 'not installed')}, left as it is")
            continue
        out = run(f"pm disable-user --user 0 {p}")
        print(f"  {p}: {'off' if 'disabled-user' in out else 'REFUSED: ' + out[:120]}")
    for (table, name), value in settings.items():
        run(f"settings put {table} {name} {value}")
        print(f"  {name}: {setting_now(table, name)}")
    if dns:
        run(f"settings put global private_dns_specifier {dns}; settings put global private_dns_mode hostname")
        print(f"  private DNS: {' '.join(dns_now())}")


def check():
    packages, settings, dns = read_list()
    now = states()
    drift = [p for p in packages if now.get(p) == "enabled"]
    for p in drift:
        print(f"  {p}: on, the list has it off")
    for (table, name), value in settings.items():
        if setting_now(table, name) != value:
            drift.append(name)
            print(f"  {name}: {setting_now(table, name)}, should be {value}")
    if dns and dns_now() != ("hostname", dns):
        drift.append("private-dns")
        print(f"  private DNS: {' '.join(dns_now())}, should be hostname {dns}")
    print("  everything as listed" if not drift else f"  {len(drift)} drifted, `python tools/tv.py apply` puts it right")
    return 1 if drift else 0


def restore():
    if not BEFORE.exists():
        raise SystemExit("no tv/before.txt, so nothing to restore to")
    lines = [l for l in BEFORE.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    for l in lines:
        if l.startswith("setting "):
            _, table, name, was = l.split(None, 3)
            run(f"settings delete {table} {name}" if was == "null" else f"settings put {table} {name} {was}")
            print(f"  {name}: {setting_now(table, name)}")
    before = dict(l.split(None, 1) for l in lines if not l.startswith("setting "))
    now = states()
    for p, was in before.items():
        if p.startswith("private-dns"):
            continue
        if was.strip() == "enabled" and now.get(p) == "disabled":
            out = run(f"pm enable --user 0 {p}")
            print(f"  {p}: {'back on' if 'enabled' in out else out[:120]}")
    mode, spec = before.get("private-dns-mode", "null").strip(), before.get("private-dns-specifier", "null").strip()
    run("settings delete global private_dns_mode" if mode == "null" else f"settings put global private_dns_mode {mode}")
    run("settings delete global private_dns_specifier" if spec == "null" else f"settings put global private_dns_specifier {spec}")
    print(f"  private DNS: {' '.join(dns_now())}")
    if KEEPER in run(f"pm list packages {KEEPER}"):
        print(f"  the keeper: {run(f'pm uninstall {KEEPER}')}")


def install_keeper():
    """Over the same ADB connection, in base64 chunks: the androidtv integration only takes shell
    commands, and a 13 KB app is a handful of them"""
    if not KEEPER_APK.exists():
        raise SystemExit("no tv/keeper/build/keeper.apk, run tools/tv-keeper.sh first")
    apk = KEEPER_APK.read_bytes()
    text = base64.b64encode(apk).decode()
    tmp = "/data/local/tmp/keeper"
    run(f"rm -f {tmp}.b64 {tmp}.apk")
    for i in range(0, len(text), 3000):
        run(f"echo -n '{text[i:i + 3000]}' >> {tmp}.b64")
    run(f"base64 -d {tmp}.b64 > {tmp}.apk")
    got = run(f"md5sum {tmp}.apk").split()[0]
    if got != hashlib.md5(apk).hexdigest():
        raise SystemExit(f"the copy on the TV doesn't match ({got}), nothing installed")
    print("  copied:", run(f"pm install -r {tmp}.apk").splitlines()[-1])
    run(f"pm grant {KEEPER} android.permission.WRITE_SECURE_SETTINGS")
    run(f"am start -n {KEEPER}/.Main")
    run(f"rm -f {tmp}.b64 {tmp}.apk")
    granted = "granted=true" in run(f"dumpsys package {KEEPER} | grep WRITE_SECURE_SETTINGS")
    job = KEEPER in run(f"dumpsys jobscheduler | grep {KEEPER} | head -3")
    print(f"  permission granted: {granted}, 15-minute job scheduled: {job}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "run" and len(sys.argv) > 2:
        print(run(sys.argv[2]))
    elif what in ("apply", "restore"):
        {"apply": apply, "restore": restore}[what]()
    elif what == "install-keeper":
        install_keeper()
    elif what == "check":
        sys.exit(check())
    else:
        print(__doc__)
        sys.exit(2)
