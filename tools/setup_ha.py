#!/usr/bin/env python3
"""The Home Assistant side of house.toml, every step in order. tools/ha-apps.sh runs it after the
scenario tests pass; run it by hand only when you know the tests don't matter for what changed.

Safe to rerun, and meant to be: each step looks at what's there and only changes what doesn't match.
Steps that need a device or an integration you haven't added yet say so and move on, so the first
run gets what it can and a rerun after adding things picks up the rest.

  python tools/setup_ha.py              everything
  python tools/setup_ha.py lights tv    just those steps (names below, in STEPS)
  python tools/setup_ha.py --plan       ask Home Assistant everything and change nothing: each
                                        change a step would make gets printed instead, and only
                                        when it really is a change (PLAN=1 does the same)

Needs the token in ~/.config/ha-hub/token, the Hub's host scripts run (50-screen.sh writes the
broker login, 70-voice.sh starts the satellite), and SSH to the Hub. Standard library only.
"""
import difflib
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import build as builder  # noqa: E402
import ha as hapi  # noqa: E402
import house as housefile  # noqa: E402

PLAN = os.environ.get("PLAN") == "1" or "--plan" in sys.argv
# a plan waits for nothing, since nothing it asked for is happening
sleep = (lambda seconds: None) if PLAN else time.sleep
H = housefile.load()
# what the house calls its printers and its vacuum ([names] in house.toml)
NAMES = {**housefile.DEFAULTS["names"], **H["names"]}
HUB_SSH = os.environ.get("HUB") or H["hub"]["ssh"]
HA_HOST = os.environ.get("HA_HOST") or H["home_assistant"]["host"]
_ws = None

# The helpers' starting values, set once each (the first time the helper exists) and yours after
# that: /config/.ha-hub-defaults on Home Assistant remembers which are done. Neutral numbers, not
# anyone's routine; the Routines page of the dashboard is where they become yours. tests/house.py
# reads this list too, so the bench starts where a fresh house does
DEFAULTS = [
    ("input_boolean.greet_on_arrival", "input_boolean/turn_on", {}),
    ("input_boolean.vacuum_docks_on_arrival", "input_boolean/turn_on", {}),
    ("input_boolean.movie_mutes_jarvis", "input_boolean/turn_on", {}),
    ("input_number.jarvis_quiet_volume", "input_number/set_value", {"value": 0.45}),
    ("input_number.jarvis_normal_volume", "input_number/set_value", {"value": 0.66}),
    ("input_number.sleep_goal", "input_number/set_value", {"value": 8}),
    ("input_number.morning_prep_minutes", "input_number/set_value", {"value": 45}),
    ("input_number.commute_minutes", "input_number/set_value", {"value": 30}),
    ("input_number.sunrise_minutes", "input_number/set_value", {"value": 30}),
    ("input_number.desk_in_use_watts", "input_number/set_value", {"value": 50}),
    ("input_number.wind_down_hours", "input_number/set_value", {"value": 3}),
    ("input_number.arrive_early_minutes", "input_number/set_value", {"value": 10}),
    ("input_datetime.work_arrival", "input_datetime/set_datetime", {"time": "09:00:00"}),
    # a new date-and-time helper starts at midnight today, which reads as "already happened today"
    # (a load done, a ring tonight). Long ago means never
    ("input_datetime.lights_blend_until", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.washer_done_at", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.doorbell_last_ring", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.doorbell_last_lingering", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.probably_asleep_since", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.dozed_off_at", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.vacuum_asked_at", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.house_error_at", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_datetime.wake_up_backstop_at", "input_datetime/set_datetime", {"datetime": "2000-01-01 00:00:00"}),
    ("input_select.wake_up_workdays", "input_select/select_option", {"option": "Sunrise and alarm"}),
    ("input_select.wake_up_weekends", "input_select/select_option", {"option": "Off"}),
    ("input_select.vacuum_when_leaving", "input_select/select_option", {"option": "Ask"}),
    # the house's off switches (packages/controls.yaml) start on
    ("input_boolean.auto_vacuum", "input_boolean/turn_on", {}),
    ("input_boolean.auto_clock_modes", "input_boolean/turn_on", {}),
    ("input_boolean.auto_welcome", "input_boolean/turn_on", {}),
    ("input_boolean.auto_bedtime_nudge", "input_boolean/turn_on", {}),
    ("input_boolean.auto_asleep", "input_boolean/turn_on", {}),
    ("input_boolean.auto_briefing", "input_boolean/turn_on", {}),
    ("input_boolean.auto_security", "input_boolean/turn_on", {}),
    ("input_boolean.auto_doorbell", "input_boolean/turn_on", {}),
    ("input_boolean.auto_laundry", "input_boolean/turn_on", {}),
    ("input_boolean.auto_printers", "input_boolean/turn_on", {}),
    ("input_boolean.auto_desk", "input_boolean/turn_on", {}),
    ("input_boolean.auto_journal", "input_boolean/turn_on", {}),
]

# the labels the packages read (packages/lights.yaml, packages/vacuum.yaml)
LABELS = {f"light_{x}": f"Light {x.replace('_', ' ')}" for x in housefile.LAYERS + housefile.ROLES}
LABELS.update({"room_door": "Room door", "vacuum_room": "Vacuum room"})

WAKE_NAMES = {"hey_jarvis": "Hey Jarvis", "okay_nabu": "Okay Nabu", "hey_mycroft": "Hey Mycroft"}


# -- talking to Home Assistant ------------------------------------------------------------------

def ws(cmd, strict=False):
    global _ws
    if PLAN and not reads(cmd):
        return planned(cmd)
    if _ws is None:
        _ws = hapi.WS()
    return _ws.call(cmd, strict=strict)


def rest(method, path, body=None):
    if PLAN and method != "GET":
        return planned_rest(method, path.lstrip("/"), body)
    return hapi.rest(method, "/" + path.lstrip("/"), body, strict=False)


def reconnect():
    global _ws
    _ws = None


def sup(method, endpoint, data=None):
    cmd = {"type": "supervisor/api", "method": method, "endpoint": endpoint, "timeout": 600}
    if data is not None:
        cmd["data"] = data
    return ws(cmd)


def say(*a):
    print(*a, flush=True)


def ssh(target, cmd, data=None):
    r = subprocess.run(["ssh", "-4", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", target, cmd],
                       input=data, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def ssh_ha(cmd, data=None):
    if PLAN and not (cmd.lstrip().startswith("cat ") and ">" not in cmd.replace("2>/dev/null", "") and data is None):
        would("run on Home Assistant: " + cmd.strip().splitlines()[0][:100])
        return ""
    return ssh(f"root@{HA_HOST}", cmd, data)


# -- plan mode: the change, printed instead of made ---------------------------------------------
# Later steps see the house as it was, so one that needs an earlier step's change (a rename, a new
# entry) can say it's missing something that a real run would have made.

def would(what):
    say("  would " + what)


def reads(cmd):
    t = cmd["type"]
    if t == "supervisor/api":
        return cmd.get("method") == "get"
    return t in ("get_states", "lovelace/config") or t.endswith(("/list", "/get", "/info", "/progress", "get_segments"))


def same(a, b):
    """Equal the way Home Assistant means it: a list is a set, nothing is nothing"""
    def norm(x):
        if x in (None, "", [], {}):
            return None
        if isinstance(x, (list, set, tuple)):
            return sorted(map(str, x))
        if isinstance(x, float) and x.is_integer():
            return int(x)
        return x
    return norm(a) == norm(b)


def changes(current, wanted, skip=()):
    return [f"{k} {current.get(k)!r} -> {v!r}" for k, v in wanted.items() if k not in skip and not same(current.get(k), v)]


_restart_next = set()


def planned(cmd):
    t = cmd["type"]
    if t == "config/entity_registry/update":
        eid = cmd["entity_id"]
        cur = ws({"type": "config/entity_registry/get", "entity_id": eid}) or {}
        if not cur:
            would(f"change {eid}, which isn't there (yet)")
            return {}
        out = changes(cur, cmd, skip=("type", "entity_id", "new_entity_id", "options", "options_domain"))
        if cmd.get("new_entity_id", eid) != eid:
            out.insert(0, f"rename to {cmd['new_entity_id']}")
        if "options" in cmd:
            have = (cur.get("options") or {}).get(cmd["options_domain"]) or {}
            out += [f"{cmd['options_domain']} option {k} {have.get(k)!r} -> {v!r}" for k, v in cmd["options"].items() if not same(have.get(k), v)]
        if out:
            would(f"change {eid}: " + "; ".join(out))
        return {"entity_entry": cur}
    if t == "config/device_registry/update":
        d = next((x for x in devices() if x["id"] == cmd["device_id"]), {})
        out = changes(d, cmd, skip=("type", "device_id"))
        if out:
            would(f"change device {d.get('name_by_user') or d.get('name')}: " + "; ".join(out))
        return {}
    if t == "config/area_registry/update":
        a = next((x for x in ws({"type": "config/area_registry/list"}) or [] if x["area_id"] == cmd["area_id"]), {})
        out = changes(a, cmd, skip=("type", "area_id"))
        if out:
            would(f"change area {a.get('name')}: " + "; ".join(out))
        return {}
    if t == "homeassistant/expose_entity":
        have = (ws({"type": "homeassistant/expose_entity/list"}) or {}).get("exposed_entities") or {}
        flip = [e for e in cmd["entity_ids"] if bool((have.get(e) or {}).get("conversation")) != cmd["should_expose"]]
        if flip:
            would(("show Jarvis " if cmd["should_expose"] else "hide from Jarvis ") + ", ".join(flip))
        return {}
    if t == "assist_pipeline/pipeline/update":
        cur = next((p for p in (ws({"type": "assist_pipeline/pipeline/list"}) or {}).get("pipelines", [])
                    if p["id"] == cmd["pipeline_id"]), {})
        out = changes(cur, cmd, skip=("type", "pipeline_id"))
        if out:
            would(f"change pipeline {cur.get('name')}: " + "; ".join(out))
        return {}
    if t == "assist_pipeline/pipeline/set_preferred":
        if (ws({"type": "assist_pipeline/pipeline/list"}) or {}).get("preferred_pipeline") != cmd["pipeline_id"]:
            would(f"make pipeline {cmd['pipeline_id']} the preferred one")
        return {}
    if t == "lovelace/config/save":
        cur = ws({"type": "lovelace/config", "url_path": cmd["url_path"]})
        if cur != cmd["config"]:
            n = sum(1 for _ in difflib_lines(cur, cmd["config"]))
            would(f"save dashboard {cmd['url_path']} ({n} lines differ)")
        return {}
    if t == "supervisor/api":
        ep = cmd["endpoint"]
        slug = ep.split("/")[2] if ep.count("/") >= 2 else ep
        if ep.endswith("/options"):
            cur = (sup("get", f"/addons/{slug}/info") or {}).get("options") or {}
            new = (cmd.get("data") or {}).get("options") or {}
            # names only: an app's options can hold a password
            diff = [k for k, v in new.items() if not same(cur.get(k), v)]
            if diff:
                would(f"set {slug}'s {', '.join(diff)}")
                _restart_next.add(slug)
        elif ep.endswith(("/restart", "/start")):
            if slug in _restart_next:
                would(f"restart {slug}")
        else:
            would(f"{cmd.get('method')} {ep}")
        return {}
    if t == "backup/config/update":
        would("include " + ", ".join(cmd.get("create_backup", {}).get("include_addons", [])) + " in the backups")
        return {}
    would(t + " " + json.dumps({k: v for k, v in cmd.items() if k != "type"}, ensure_ascii=False)[:160])
    return {}


def difflib_lines(a, b):
    return (l for l in difflib.unified_diff(json.dumps(a, indent=1, sort_keys=True).splitlines(),
                                            json.dumps(b, indent=1, sort_keys=True).splitlines(), n=0, lineterm="")
            if l[:1] in "+-" and l[:3] not in ("+++", "---"))


def planned_rest(method, path, body):
    if path.startswith("api/services/"):
        domain, service = path.split("/")[2:4]
        eid = (body or {}).get("entity_id")
        st = (states().get(eid) or {}).get("state") if isinstance(eid, str) else None
        want = {"select_option": (body or {}).get("option"), "turn_off": "off", "turn_on": "on"}.get(service)
        if service == "set_value":
            want = (body or {}).get("value")
            if st is not None and want is not None and domain != "input_text":
                try:
                    if float(st) == float(want):
                        return {}
                except ValueError:
                    pass
        if st is not None and want is not None and str(st) == str(want):
            return {}
        would(f"call {domain}.{service} for {eid} ({st!r} now): {json.dumps({k: v for k, v in (body or {}).items() if k != 'entity_id'}, ensure_ascii=False)[:120]}")
        return {}
    if path.startswith("api/config/automation/config/"):
        cur = hapi.rest("GET", "/" + path, strict=False) or {}
        cur = {k: v for k, v in cur.items() if k != "id"}
        if cur != {k: v for k, v in (body or {}).items() if k != "id"}:
            would(f"save automation {path.rsplit('/', 1)[1]} ({sum(1 for _ in difflib_lines(cur, body))} lines differ)")
        return {}
    would(f"{method} {path} {json.dumps(body, ensure_ascii=False)[:160] if body else ''}")
    return {}


def states():
    return {s["entity_id"]: s for s in (ws({"type": "get_states"}) or [])}


def registry():
    return ws({"type": "config/entity_registry/list"}) or []


def devices():
    return ws({"type": "config/device_registry/list"}) or []


def entries(domain):
    return ws({"type": "config_entries/get", "domain": domain}) or []


def areas():
    return {a["name"].lower(): a["area_id"] for a in (ws({"type": "config/area_registry/list"}) or [])}


def update_entity(entity_id, **kw):
    return ws({"type": "config/entity_registry/update", "entity_id": entity_id, **kw})


def expose(ids, on=True, keep=()):
    have = states()
    ids = [e for e in ids if e in have and e not in keep]
    if ids:
        ws({"type": "homeassistant/expose_entity", "assistants": ["conversation"], "entity_ids": ids,
            "should_expose": on})


def flow(handler, *steps):
    """Start a config flow and send it the steps, one after another. The last answer comes back"""
    r = rest("POST", "api/config/config_entries/flow", {"handler": handler})
    for step in steps:
        if not r or "flow_id" not in r:
            return r
        r = rest("POST", f"api/config/config_entries/flow/{r['flow_id']}", step)
    return r


def rename(entity_id, new_id):
    if entity_id == new_id:
        return True
    taken = {e["entity_id"] for e in registry()}
    if new_id in taken:
        say(f"  {new_id} is taken already, {entity_id} keeps its name")
        return False
    if update_entity(entity_id, new_entity_id=new_id) is None:
        return False
    # a person follows its trackers by entity id and isn't told about a rename, so without this
    # it's unknown from then on (the recorder and Proximity do follow)
    if entity_id.startswith("device_tracker."):
        for p in (ws({"type": "person/list"}) or {}).get("storage", []):
            if entity_id in p.get("device_trackers", []):
                ws({"type": "person/update", "person_id": p["id"], "name": p["name"], "user_id": p.get("user_id"),
                    "device_trackers": [new_id if t == entity_id else t for t in p["device_trackers"]]})
    return True


def common_prefix(ids):
    """The longest run of whole words every object id starts with"""
    parts = [i.split("_") for i in ids]
    out = []
    for words in zip(*parts):
        if len(set(words)) != 1:
            break
        out.append(words[0])
    return "_".join(out)


def rename_device(entity_id, new_prefix):
    """Every entity on entity_id's device that shares its name moves to the new prefix:
    device_tracker.alexs_iphone and sensor.alexs_iphone_ssid become device_tracker.phone and
    sensor.phone_ssid. Entities already on the new prefix are left alone"""
    reg = registry()
    e = next((x for x in reg if x["entity_id"] == entity_id), None)
    if e is None:
        say(f"  {entity_id} isn't in Home Assistant (yet?), skipped")
        return
    group = [x for x in reg if e.get("device_id") and x.get("device_id") == e["device_id"]] or [e]
    objs = [x["entity_id"].split(".", 1)[1] for x in group]
    old = common_prefix(objs) or entity_id.split(".", 1)[1]
    if old == new_prefix:
        return
    moved = 0
    for x in group:
        domain, obj = x["entity_id"].split(".", 1)
        if obj == old:
            new = new_prefix
        elif obj.startswith(old + "_"):
            new = new_prefix + obj[len(old):]
        else:
            continue
        if rename(x["entity_id"], f"{domain}.{new}"):
            moved += 1
    say(f"  {old}_... -> {new_prefix}_... ({moved} entities)")


def prompt():
    """ha/context/about.md, then the house's about.local.md if it's there, comments out and the
    house's words in (tools/build.py)"""
    out = []
    for p in (ROOT / "ha" / "context" / "about.md", housefile.file("about")):
        if p.is_file():
            text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
            out.append(builder.render(text, H))
    return "\n\n".join(x for x in out if x) + "\n"


def words():
    out = []
    for p in (ROOT / "hub" / "parakeet-words.txt", housefile.file("words")):
        if p.is_file():
            out += [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    return list(dict.fromkeys(out))


# -- the steps ----------------------------------------------------------------------------------

def app(slug, edit, network=None):
    """Install a Supervisor app if it isn't, set its options with edit(options), (re)start it"""
    if not (sup("get", f"/store/addons/{slug}") or {}).get("installed"):
        say(f"installing {slug}")
        sup("post", f"/store/addons/{slug}/install")
    info = sup("get", f"/addons/{slug}/info") or {}
    options = dict(info.get("options") or {})
    edit(options)
    body = {"options": options}
    if network:
        body["network"] = network
    sup("post", f"/addons/{slug}/options", body)
    sup("post", f"/addons/{slug}/{'restart' if info.get('state') == 'started' else 'start'}")
    say(f"{slug}: {(sup('get', f'/addons/{slug}/info') or {}).get('state')}")


def step_apps():
    # Terminal & SSH with this computer's public key, so the rest can copy config in
    keys = [p for p in (pathlib.Path.home() / ".ssh").glob("id_*.pub")]
    if not keys:
        say("no ~/.ssh/id_*.pub: make a key (ssh-keygen -t ed25519) and run this again")
    else:
        pub = keys[0].read_text().strip()
        app("core_ssh", lambda o: o.update(authorized_keys=[pub]), {"22/tcp": 22})
    # Mosquitto with the login the Hub's services use (host/50-screen.sh wrote it)
    env = ssh(HUB_SSH, "cat /etc/ha-hub/mqtt.env")
    if env:
        kv = dict(l.split("=", 1) for l in env.split() if "=" in l)
        app("core_mosquitto", lambda o: o.update(logins=[{"username": kv["MQTT_USER"], "password": kv["MQTT_PASS"]}]))
    else:
        say("couldn't read /etc/ha-hub/mqtt.env on the Hub: run host/50-screen.sh first")
    # Whisper as the fallback speech to text, small with the house's words as its prompt and its
    # own speech filter (vad_clip, which also stops it inventing "Thanks for watching!" from
    # background noise). Parakeet on the Hub is the main one (host/76-parakeet.sh)
    vocab = ", ".join(words()) + "."
    app("core_whisper", lambda o: o.update(model="small-int8", language="en", vad_clip=True, initial_prompt=vocab))
    app("core_piper", lambda o: o.update(voice="en_US-lessac-medium"))


def step_discovered():
    """Discovered integrations want a click each. These are the clicks, for ours only: Mosquitto,
    the Whisper and Piper apps, and the satellite (its mDNS name starts with lva-)"""
    need = {"mqtt": 1, "wyoming": 2, "esphome": 1}
    for _ in range(30):
        for f in ws({"type": "config_entries/flow/progress"}) or []:
            name = (f.get("context", {}).get("title_placeholders") or {}).get("name", "")
            src = f.get("context", {}).get("source")
            if (f["handler"] in ("mqtt", "wyoming") and src == "hassio") or (f["handler"] == "esphome" and name.startswith("lva-")):
                rest("POST", f"api/config/config_entries/flow/{f['flow_id']}", {})
                say(f"added {f['handler']} {name}")
        have = {}
        for e in ws({"type": "config_entries/get"}) or []:
            have[e["domain"]] = have.get(e["domain"], 0) + 1
        missing = [d for d, n in need.items() if have.get(d, 0) < n]
        if not missing:
            return
        sleep(10)
    say(f"still waiting on: {', '.join(missing)} (run this again once they show up)")


def step_local_model():
    """A small model on the Hub (host/80-ollama.sh), only with voice.local_model in house.toml"""
    model = H["voice"]["local_model"]
    if not model:
        return
    entry = next(iter(entries("ollama")), None)
    if entry is None:
        r = flow("ollama", {"url": f"http://{H['hub']['address']}:11434"})
        entry = (r or {}).get("result")
        if not entry:
            say("Ollama:", (r or {}).get("errors") or r)
            return
    eid = entry["entry_id"]
    agent = {"model": model, "prompt": prompt(), "llm_hass_api": ["assist"], "num_ctx": 8192,
             "max_history": 10, "keep_alive": -1, "think": False}
    subs = ws({"type": "config_entries/subentries/list", "entry_id": eid}) or []
    sid = next((s["subentry_id"] for s in subs if s["title"] == "Jarvis (local)"), None)
    body = {"handler": [eid, "conversation"]} | ({"subentry_id": sid} if sid else {})
    f = rest("POST", "api/config/config_entries/subentries/flow", body)
    if f and "flow_id" in f:
        rest("POST", f"api/config/config_entries/subentries/flow/{f['flow_id']}",
             agent | ({} if sid else {"name": "Jarvis (local)"}))
    say(f"local agent: {model}")


def step_system_monitor():
    """The VM from the inside (and Settings, System, Hardware). The whole box comes from hub-stats"""
    if not entries("systemmonitor"):
        flow("systemmonitor", {})
        sleep(5)
    for e in ("disk_usage", "load_1_min", "memory_free", "memory_use", "memory_usage", "processor_use", "swap_usage"):
        update_entity(f"sensor.system_monitor_{e}", disabled_by=None)


def step_tv():
    """The Fire TV over ADB, from fire_tv.address. The first connection pops up "Allow USB
    debugging?" on the TV, which someone has to accept there. The integration can't change a TV's
    address and has no reconfigure, so a TV that moved gets its entry removed and added again (the
    ADB key stays in /config/.storage, so the TV doesn't ask again)"""
    tv_ip = H["fire_tv"]["address"]
    if not tv_ip:
        return
    for e in entries("androidtv"):
        if e["title"] != tv_ip:
            rest("DELETE", f"api/config/config_entries/entry/{e['entry_id']}")
            say("TV moved, removed its entry for the old address")
    if not entries("androidtv"):
        flow("androidtv", {"host": tv_ip, "device_class": "firetv", "port": 5555, "more_options": {}})
        entry = next(iter(entries("androidtv")), None)
        if not entry:
            say(f"Fire TV at {tv_ip} didn't answer: is ADB debugging on, and was the prompt accepted?")
            return
        f = rest("POST", "api/config/config_entries/options/flow", {"handler": entry["entry_id"]})
        opts = {"get_sources": True, "exclude_unnamed_apps": True, "screencap_interval": 0}
        for package, name in H["fire_tv"]["apps"].items():
            rest("POST", f"api/config/config_entries/options/flow/{f['flow_id']}", {"apps": "NewApp", **opts})
            rest("POST", f"api/config/config_entries/options/flow/{f['flow_id']}", {"app_id": package, "app_name": name})
        rest("POST", f"api/config/config_entries/options/flow/{f['flow_id']}", opts)
        sleep(5)
        say(f"TV added at {tv_ip} (accept the prompt on the TV if it's the first time)")
    entry = next(iter(entries("androidtv")), None)
    if not entry:
        return
    # by entry, not by name: a re-added TV can come back under its old entity id
    for e in registry():
        if e.get("config_entry_id") == entry["entry_id"]:
            if e["entity_id"].startswith("media_player."):
                rename(e["entity_id"], "media_player.fire_tv")
                if e.get("device_id"):
                    ws({"type": "config/device_registry/update", "device_id": e["device_id"], "name_by_user": H["fire_tv"]["name"],
                        "area_id": areas().get(H["fire_tv"]["area"].lower())})
            elif e["entity_id"].startswith("remote."):
                rename(e["entity_id"], "remote.fire_tv_remote")
    # every run: off is the remote's short press (ambient mode) and only from awake, on is the same
    # press from ambient or fully off, so neither one ever flips the TV the wrong way. A screenshot a
    # minute for the dashboard (refused under Netflix and the other DRM apps)
    f = rest("POST", "api/config/config_entries/options/flow", {"handler": entry["entry_id"]})
    if f and "flow_id" in f:
        rest("POST", f"api/config/config_entries/options/flow/{f['flow_id']}", {
            "get_sources": True, "exclude_unnamed_apps": True, "screencap_interval": 1,
            "turn_on_command": "dumpsys power | grep -q mWakefulness=Awake || input keyevent KEYCODE_POWER",
            "turn_off_command": "dumpsys power | grep -q mWakefulness=Awake && input keyevent KEYCODE_POWER"})


def step_cloud_agent():
    """The cloud agent behind "Hey Jarvis": whichever conversation agent voice.cloud_agent names,
    renamed conversation.jarvis_cloud, with ha/context/about.md as its prompt and Home Assistant's
    Assist tools on. The provider's own settings (model, thinking, web search) are left as they are:
    every provider asks for different ones, so they're set in its options, once, by you. The prompt
    goes in through the agent's reconfigure flow, filled from its own form, so any provider whose
    form has a prompt field works the same way"""
    agent = H["voice"]["cloud_agent"]
    if not agent:
        return
    reg = {e["entity_id"]: e for e in registry()}
    e = reg.get(agent) or reg.get("conversation.jarvis_cloud")
    if e is None:
        say(f"{agent} isn't in Home Assistant yet: add the provider's integration and its conversation agent first")
        return
    if e["entity_id"] != "conversation.jarvis_cloud":
        rename(e["entity_id"], "conversation.jarvis_cloud")
    update_entity("conversation.jarvis_cloud", name="Jarvis (cloud)")
    entry, sub = e.get("config_entry_id"), e.get("config_subentry_id")
    if not entry or not sub:
        say("cloud agent renamed; set its prompt by hand (it isn't a sub-entry this tool can reconfigure)")
        return
    f = rest("POST", "api/config/config_entries/subentries/flow",
             {"handler": [entry, "conversation"], "subentry_id": sub})
    text = prompt()
    for _ in range(4):
        if not f or f.get("type") != "form":
            break
        body = {}
        for field in f.get("data_schema") or []:
            name = field.get("name")
            current = (field.get("description") or {}).get("suggested_value", field.get("default"))
            if name == "prompt":
                body[name] = text
            elif name == "llm_hass_api":
                body[name] = ["assist"]
            elif current is not None:
                body[name] = current
        f = rest("POST", f"api/config/config_entries/subentries/flow/{f['flow_id']}", body)
    ok = f and (f.get("type") == "abort" and "success" in str(f.get("reason", "")) or f.get("type") == "create_entry")
    say("cloud agent: prompt set" if ok else f"cloud agent: the prompt didn't go in ({(f or {}).get('errors') or (f or {}).get('reason')})")


def step_writer():
    """The AI task that writes the welcome home from the digest's kit (hub/hub_digest.py): whichever
    one voice.writer names, renamed ai_task.jarvis_writer. The kit is text off the internet, and an
    AI task never gets the house's tools, which is the point. Its web search is the provider's own
    setting and is best off, so the words come from the kit and nothing else"""
    task = H["voice"]["writer"]
    if not task:
        return
    reg = {e["entity_id"]: e for e in registry()}
    e = reg.get(task) or reg.get("ai_task.jarvis_writer")
    if e is None:
        say(f"{task} isn't in Home Assistant yet: add the provider's AI task first")
        return
    if e["entity_id"] != "ai_task.jarvis_writer":
        rename(e["entity_id"], "ai_task.jarvis_writer")
    update_entity("ai_task.jarvis_writer", name="Jarvis (writer)")
    say("writer: ai_task.jarvis_writer")


def step_speech():
    """Kokoro and Parakeet on the Hub as Wyoming engines, by the Hub's address (mDNS lookups fail
    now and then, and every one of those is a deaf or a mute assistant). The ports are fenced to
    the VM (host/74-kokoro.sh, host/76-parakeet.sh), which is where these connections come from"""
    address = H["hub"]["address"]
    if not address:
        say("hub.address is empty, skipping Kokoro and Parakeet")
        return
    titles = {e["title"] for e in entries("wyoming")}
    for title, port in (("kokoro", 10210), ("parakeet", 10310)):
        if title not in titles:
            r = flow("wyoming", {"host": address, "port": port})
            say(f"{title}:", (r or {}).get("type"), (r or {}).get("errors") or "")


def step_pipelines():
    """The voice pipeline: Parakeet (Whisper if it isn't there), the built-in intents first
    (instant, free), then the cloud agent, speaking as Kokoro (Piper if it isn't there)"""
    have = states()
    kokoro = "tts.kokoro" in have
    piper_voice = "jarvis-high" if "piper_jarvis" in H["extras"]["install"] else "en_US-lessac-medium"
    engine = ("conversation.jarvis_cloud" if "conversation.jarvis_cloud" in have else
              ("conversation.jarvis_local" if any(k.startswith("conversation.jarvis_local") for k in have) else "conversation.home_assistant"))
    if engine == "conversation.jarvis_local":
        engine = next(k for k in have if k.startswith("conversation.jarvis_local"))
    cfg = {"name": "Jarvis", "language": "en", "conversation_language": "en", "conversation_engine": engine,
           "stt_engine": "stt.parakeet" if "stt.parakeet" in have else "stt.faster_whisper", "stt_language": "en",
           "tts_engine": "tts.kokoro" if kokoro else "tts.piper",
           "tts_language": H["voice"]["tts_language"] if kokoro else "en_US",
           "tts_voice": H["voice"]["tts_voice"] if kokoro else piper_voice,
           "wake_word_entity": None, "wake_word_id": None, "prefer_local_intents": True}
    listing = ws({"type": "assist_pipeline/pipeline/list"}) or {"pipelines": []}
    found = next((p for p in listing["pipelines"] if p["name"] == "Jarvis"), None) \
        or next((p for p in listing["pipelines"] if p["id"] == listing.get("preferred_pipeline")), None)
    if found:
        ws({"type": "assist_pipeline/pipeline/update", "pipeline_id": found["id"], **cfg})
        pid = found["id"]
    else:
        pid = (ws({"type": "assist_pipeline/pipeline/create", **cfg}) or {}).get("id")
    if pid:
        ws({"type": "assist_pipeline/pipeline/set_preferred", "pipeline_id": pid})
    wake = H["voice"]["wake_word"]
    selects = [("select.hub_500_voice_wake_word", WAKE_NAMES.get(wake, wake)), ("select.hub_500_voice_assistant", "Jarvis"),
               # 1.25 s of silence: Smart Turn on the satellite ends a finished sentence much sooner
               # (host/70-voice.sh), so this only has to wait out a pause mid-thought
               ("select.hub_500_voice_finished_speaking_detection", "relaxed")]
    # Two "Hey Jarvis" detectors at once: microWakeWord at 90% and openWakeWord's own model at its
    # default 50%. They miss different utterances, which is the whole point (docs/voice.md). Only
    # Hey Jarvis has both
    if wake == "hey_jarvis":
        selects += [("select.hub_500_voice_wake_word_2", "Hey Jarvis (OWW)"), ("select.hub_500_voice_assistant_2", "Jarvis")]
    for entity, option in selects:
        if entity in have:
            rest("POST", "api/services/select/select_option", {"entity_id": entity, "option": option})
    if wake == "hey_jarvis":
        for entity, value in (("number.hub_500_voice_wake_word_1_sensitivity", 0.90),
                              ("number.hub_500_voice_wake_word_2_sensitivity", 0.50)):
            if entity in have:
                rest("POST", "api/services/number/set_value", {"entity_id": entity, "value": value})
    # no thinking sound: the LED ring goes white while it thinks instead (hub_ring.py)
    if "switch.hub_500_voice_thinking_sound" in have:
        rest("POST", "api/services/switch/turn_off", {"entity_id": "switch.hub_500_voice_thinking_sound"})
    say(f"pipeline: {WAKE_NAMES.get(wake, wake)} -> {engine}")


ICONS = (("living", "mdi:sofa"), ("kitchen", "mdi:stove"), ("bed", "mdi:bed"), ("bath", "mdi:shower"),
         ("office", "mdi:desk"), ("study", "mdi:desk"), ("hall", "mdi:door"), ("dining", "mdi:silverware-fork-knife"))


def step_rooms():
    """The rooms, the way you say them, and the Hub's two devices in the Hub's room: voice
    commands without a device name ("turn the volume down") resolve through the satellite's area"""
    have = areas()
    aliases = H["rooms"].get("aliases", {})
    for name in H["rooms"]["names"]:
        icon = next((i for k, i in ICONS if k in name.lower()), "mdi:home-outline")
        if name.lower() not in have:
            have[name.lower()] = (ws({"type": "config/area_registry/create", "name": name, "icon": icon}) or {}).get("area_id")
        ws({"type": "config/area_registry/update", "area_id": have[name.lower()], "aliases": list(aliases.get(name, []))})
    hub_area = have.get(H["hub"]["area"].lower())
    if hub_area:
        for d in devices():
            if d.get("name") in ("Hub 500", "Hub 500 Voice") and d.get("area_id") != hub_area:
                ws({"type": "config/device_registry/update", "device_id": d["id"], "area_id": hub_area})
        # entity ids pick up the area they were born in (sensor.living_room_hub_500_cpu), so drop it
        for e in registry():
            m = re.match(r"^(\w+)\.\w+?_hub_500_(\w+)$", e["entity_id"])
            if m and e.get("platform") == "mqtt":
                rename(e["entity_id"], f"{m.group(1)}.hub_500_{m.group(2)}")
    say("rooms:", ", ".join(H["rooms"]["names"]))


def step_labels():
    have = {l["label_id"] for l in (ws({"type": "config/label_registry/list"}) or [])}
    for label_id, name in LABELS.items():
        if label_id not in have:
            ws({"type": "config/label_registry/create", "name": name, "icon": "mdi:tag-outline"})


def step_renames():
    """[resident] and [devices] in house.toml, onto the standard names in docs/devices.md"""
    person = H["resident"]["person"]
    if person and person != "person.resident":
        if person in {e["entity_id"] for e in registry()}:
            rename(person, "person.resident")
    for kind, prefix in housefile.DEVICE_PREFIX.items():
        entity = H["devices"].get(kind)
        if entity:
            say(f"{kind}:")
            rename_device(entity, prefix)
    if H["devices"].get("desk_power"):
        rename(H["devices"]["desk_power"], "sensor.desk_power")
    # the doors inside count for the vacuum (packages/vacuum.yaml) and the occupancy
    for door in ("binary_sensor.bedroom_door", "binary_sensor.bathroom_door"):
        e = next((x for x in registry() if x["entity_id"] == door), None)
        if e and "room_door" not in e.get("labels", []):
            update_entity(door, labels=sorted(set(e.get("labels", [])) | {"room_door"}))
    expose(["binary_sensor.front_door", "binary_sensor.bedroom_door", "binary_sensor.bathroom_door"])


def step_lights():
    """Every [[light]]: a plug wrapped as a light if it's a switch, the entity id it should have,
    its name and the names people say, its room, its layer and jobs as labels, and Jarvis can use
    it. The light's own name goes in its aliases too: "dim the bedroom light to 10%" doesn't match
    the name alone, only an alias"""
    room = areas()
    for l in H["light"]:
        reg = {e["entity_id"]: e for e in registry()}
        src, want = l["entity"], l["becomes"]
        if src not in reg and want not in reg:
            say(f"{src}: not in Home Assistant yet, skipped")
            continue
        if src.startswith("switch.") and src in reg:
            # Switch as X keeps the switch underneath (hidden) and makes the light
            mine = next((e for e in reg.values() if e["platform"] == "switch_as_x"
                         and e.get("device_id") and e.get("device_id") == reg[src].get("device_id")), None)
            if mine is None and want not in reg:
                flow("switch_as_x", {"entity_id": src, "target_domain": "light"})
                sleep(3)
                reg = {e["entity_id"]: e for e in registry()}
                mine = next((e for e in reg.values() if e["platform"] == "switch_as_x"
                             and (e.get("device_id") == reg[src].get("device_id") or e["entity_id"] == "light." + src.split(".", 1)[1])), None)
            if mine is not None:
                rename(mine["entity_id"], want)
            expose([src], on=False)
        elif src in reg:
            rename(src, want)
        e = next((x for x in registry() if x["entity_id"] == want), None)
        if e is None:
            say(f"{want}: couldn't make it, skipped")
            continue
        labels = [x for x in e.get("labels", []) if not x.startswith("light_")]
        labels += [f"light_{l['layer']}"] + [f"light_{r}" for r in l["roles"]]
        kw = {"labels": sorted(set(labels))}
        if l["name"]:
            kw["name"] = l["name"]
            kw["aliases"] = list(dict.fromkeys([l["name"].lower()] + [a.lower() for a in l["aliases"]]))
        if l["area"]:
            kw["area_id"] = room.get(l["area"].lower())
        update_entity(want, **kw)
        expose([want])
        say(f"{want}: {l['name'] or ''}, {l['area'] or 'no room'}, {'/'.join([l['layer']] + l['roles'])}")


# step_config's undo: the files as they were before the copy, and the new ones gone again
ROLLBACK = """
  cd /tmp/ha-hub-prev || exit 1
  for f in $(find . -type f ! -name .new | sed 's|^[.]/||'); do mkdir -p "$(dirname "/config/$f")"; cp -p "$f" "/config/$f"; done
  for f in $(cat .new); do rm -f "/config/$f"; done"""


def version(repo):
    r = subprocess.run(["git", "-C", str(repo), "describe", "--always", "--dirty", "--abbrev=12"], capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def step_config():
    """The build (tools/build.py: ha/config with the house filled in and laid over) into /config.
    A file that changed gets copied, a file the last deploy put there and this one doesn't gets
    removed (/config/.ha-hub-files remembers which, so an old package can't linger and fight a new
    one), and Home Assistant restarts only when something changed, after a config check. Every
    deploy that changed something leaves a line in /config/.ha-hub-deploys: which version of this
    repo and of the house went in, so a backup says what made it"""
    changed = copy_config(copy=not PLAN)
    if PLAN:
        if changed:
            would("check the config and restart Home Assistant")
        return
    if not changed:
        say("config unchanged")
        return
    check_config()
    restart()


def copy_config(copy):
    """The build onto /config, or with copy=False only compared with it. True if anything differs"""
    built = housefile.build_dir() / "config"
    try:
        for n in builder.build(built, H):
            say("note:", n)
    except ValueError as e:
        sys.exit(f"build: {e}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(built.rglob("*")):
            if p.is_file():
                tar.add(p, arcname=p.relative_to(built).as_posix())
    script = """
      COPY=%s
      rm -rf /tmp/ha-hub-config && mkdir -p /tmp/ha-hub-config && tar -x -C /tmp/ha-hub-config
      cd /tmp/ha-hub-config && changed=0
      find . -type f | sed 's|^[.]/||' | sort > /tmp/ha-hub-files
      # what each file was before, so a failed config check can put it all back (step_config)
      rm -rf /tmp/ha-hub-prev && mkdir -p /tmp/ha-hub-prev && : > /tmp/ha-hub-prev/.new
      keep() { [ -f "/config/$1" ] && [ ! -f "/tmp/ha-hub-prev/$1" ] && mkdir -p "$(dirname "/tmp/ha-hub-prev/$1")" && cp -p "/config/$1" "/tmp/ha-hub-prev/$1"; }
      for f in $(cat /tmp/ha-hub-files); do
        cmp -s "$f" "/config/$f" && continue
        if [ -f "/config/$f" ]; then echo "changed $f"; else echo "new $f"; echo "$f" >> /tmp/ha-hub-prev/.new; fi
        [ $COPY = 1 ] && { keep "$f"; mkdir -p "$(dirname "/config/$f")"; cp "$f" "/config/$f"; }
        changed=1
      done
      if [ -f /config/.ha-hub-files ]; then
        for f in $(grep -vxF -f /tmp/ha-hub-files /config/.ha-hub-files); do
          [ -f "/config/$f" ] || continue
          echo "removed $f"
          [ $COPY = 1 ] && { keep "$f"; rm -f "/config/$f"; }
          changed=1
        done
      fi
      [ $COPY = 1 ] && { keep .ha-hub-files; keep configuration.yaml; cp /tmp/ha-hub-files /config/.ha-hub-files; }
      grep -q "^homeassistant:" /config/configuration.yaml || {
        echo "changed configuration.yaml (packages)"
        [ $COPY = 1 ] && printf "\\n# Packages: one file per feature, from the fosters-home-hub repo\\nhomeassistant:\\n  packages: !include_dir_named packages\\n" >>/config/configuration.yaml
        changed=1; }
      # the journal writes there (packages/journal.yaml)
      [ $COPY = 1 ] && mkdir -p /config/journal
      grep -q "allowlist_external_dirs" /config/configuration.yaml || {
        echo "changed configuration.yaml (allowlist_external_dirs)"
        [ $COPY = 1 ] && sed -i "s|^  packages: !include_dir_named packages$|&\\n  allowlist_external_dirs:\\n    - /config/journal|" /config/configuration.yaml
        changed=1; }
      grep -q "^    - /config/journal$" /config/configuration.yaml || {
        echo "changed configuration.yaml (/config/journal)"
        [ $COPY = 1 ] && sed -i "s|^  allowlist_external_dirs:$|&\\n    - /config/journal|" /config/configuration.yaml
        changed=1; }
      echo "result $changed" """ % ("1" if copy else "0")
    # straight over SSH even in plan mode: with COPY=0 it only compares, in /tmp
    out = ssh(f"root@{HA_HOST}", script, buf.getvalue())
    if out is None:
        sys.exit(f"couldn't reach root@{HA_HOST} over SSH (is the Terminal & SSH app running with this computer's key?)")
    lines = out.strip().splitlines()
    for l in lines[:-1]:
        if not copy:
            would(l.replace("changed ", "change ", 1).replace("new ", "add ", 1).replace("removed ", "remove ", 1))
        elif not l.startswith("changed "):
            say(" ", l)
    changed = lines[-1].endswith("1")
    if copy and changed:
        ssh_ha("cat >> /config/.ha-hub-deploys",
               f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} engine {version(ROOT)} house {version(housefile.home()) if housefile.outside() else 'in the engine'}\n".encode())
    return changed


def check_config():
    """Home Assistant's own config check on what copy_config put there. A failure puts every file
    back the way it was, so the running house and the next restart are both still the old config"""
    if ssh_ha("ha core check >/dev/null && echo ok") is None:
        ssh_ha(ROLLBACK)
        sys.exit("the config check failed, so every file went back the way it was and nothing restarted "
                 "(ha core check on the VM says why)")


def restart():
    ssh_ha("ha core restart >/dev/null")
    say("config changed, Home Assistant restarted")
    reconnect()
    sleep(20)
    for _ in range(40):
        try:
            if hapi.rest("GET", "/api/", strict=False):
                break
        except OSError:
            pass
        sleep(5)


def step_journal_log():
    """The File notifier the journal writes through, as notify.journal_log: one line per answer in
    /config/journal/journal.md, which goes with the backups (packages/journal.yaml)"""
    path = "/config/journal/journal.md"

    def entry():
        return next((e for e in ws({"type": "config_entries/get", "domain": "file"}) or [] if path in e.get("title", "")), None)

    if entry() is None:
        r = flow("file", {"next_step_id": "notify"}, {"file_path": path, "timestamp": False})
        say("journal notifier:", (r or {}).get("type"), (r or {}).get("errors") or "")
    e = entry()
    ent = next((x for x in registry() if e and x.get("config_entry_id") == e["entry_id"] and x["entity_id"].startswith("notify.")), None)
    if ent:
        rename(ent["entity_id"], "notify.journal_log")


def step_vacuum():
    """The robot vacuum's own rooms tied to the areas of the same name, which is what "clean the
    kitchen" and vacuum.clean_area use, and those areas labelled vacuum_room (packages/vacuum.yaml)"""
    vac = next((e for e in registry() if e["entity_id"] == "vacuum.robot_vacuum"), None)
    if vac is None:
        return
    # its name is the one the house calls it ([names] vacuum), which is also what "send the vacuum
    # home" hands the built-in intent (custom_sentences/en/vacuum.yaml)
    called = NAMES["vacuum"]
    update_entity("vacuum.robot_vacuum", name=called[:1].upper() + called[1:],
                  aliases=list(dict.fromkeys(["vacuum", "robot vacuum", "robot", called.lower()])))
    room = areas()
    segs = (ws({"type": "vacuum/get_segments", "entity_id": "vacuum.robot_vacuum"}) or {}).get("segments", [])
    mapping = {}
    for s in segs:
        a = room.get(s["name"].lower())
        if a:
            mapping.setdefault(a, []).append(s["id"])
        else:
            say(f"  the vacuum's room {s['name']!r} has no area of that name, skipped")
    if segs:
        update_entity("vacuum.robot_vacuum", options_domain="vacuum",
                      options={"area_mapping": mapping, "last_seen_segments": segs})
    for a in ws({"type": "config/area_registry/list"}) or []:
        labels = set(a.get("labels", []))
        want = labels | {"vacuum_room"} if a["area_id"] in mapping else labels - {"vacuum_room"}
        if want != labels:
            ws({"type": "config/area_registry/update", "area_id": a["area_id"], "labels": sorted(want)})
    say(f"vacuum rooms: {len(mapping)} of {len(segs)}")


def step_doorbell():
    """An Aqara G410 over HomeKit gets the standard doorbell names, and its faces (Aqara "signals"
    through its Matter bridge) become binary_sensor.face_<name>, the resident's face_resident.
    Another doorbell is renamed by [devices] doorbell instead (step renames)"""
    devs = devices()
    hk = next((d for d in devs if d.get("model") == "CH-C11D"
               and any(i[0].startswith("homekit_controller") for i in d["identifiers"])), None)
    mt = next((d for d in devs if (d.get("model") or "").startswith("Aqara Smart Video Doorbell")
               and any(i[0] == "matter" for i in d["identifiers"])), None)
    if hk:
        ws({"type": "config/device_registry/update", "device_id": hk["id"], "name_by_user": "Doorbell"})
        names = {"Video Doorbell": "event.doorbell_ring", "Motion Sensor": "binary_sensor.doorbell_motion",
                 "Battery Sensor": "sensor.doorbell_battery", "Security System": "alarm_control_panel.doorbell_security",
                 "Pairing Mode": "switch.doorbell_pairing_mode"}
        for e in sorted((e for e in registry() if e.get("device_id") == hk["id"]), key=lambda e: e["entity_id"]):
            tail = re.sub(r"^Doorbell |Repeater-[0-9A-F]{4}", "", e.get("original_name") or "").strip()
            domain = e["entity_id"].split(".")[0]
            new = {"camera": "camera.doorbell", "button": "button.doorbell_identify"}.get(domain) or names.get(tail)
            if new:
                rename(e["entity_id"], new)
        # Jarvis gets the battery, not Aqara's alarm panel or the switches
        expose(["alarm_control_panel.doorbell_security", "switch.doorbell_pairing_mode", "button.doorbell_identify",
                "camera.doorbell", "event.doorbell_ring", "binary_sensor.doorbell_motion"], on=False)
        expose(["sensor.doorbell_battery"])
        say("doorbell: HomeKit names")
    if mt:
        ws({"type": "config/device_registry/update", "device_id": mt["id"], "name_by_user": "Doorbell (Matter bridge)"})
        me = re.sub(r"[^a-z0-9]+", "_", H["resident"]["face"].lower()).strip("_")
        faces = 0
        for d in devs:
            if d.get("via_device_id") != mt["id"]:
                continue
            ents = [e for e in registry() if e.get("device_id") == d["id"]]
            raw = d.get("name") or ""
            # real Zigbee sensors paired to its hub come through the same bridge: [devices] names those
            if any(e["entity_id"].startswith("sensor.") for e in ents):
                continue
            if re.search(r"linger|loiter|stay", raw, re.I):
                for e in ents:
                    if e["entity_id"].startswith("binary_sensor."):
                        rename(e["entity_id"], "binary_sensor.doorbell_lingering")
                continue
            who = "unknown" if raw.lower().startswith("unknown") else (re.sub(r"\b(detected|face)\b", "", raw, flags=re.I).strip() or "unknown")
            slug = re.sub(r"[^a-z0-9]+", "_", who.lower()).strip("_")
            slug = "resident" if me and slug == me else slug
            ws({"type": "config/device_registry/update", "device_id": d["id"], "name_by_user": f"Face: {who}"})
            for e in ents:
                if e["entity_id"].startswith("binary_sensor."):
                    rename(e["entity_id"], f"binary_sensor.face_{slug}")
                    update_entity(f"binary_sensor.face_{slug}", name=f"Face: {who}")
                    expose([f"binary_sensor.face_{slug}"])
            faces += 1
        if faces:
            say(f"faces: {faces}")


def step_printers():
    """Printer temperatures and heater duty in whole numbers: Klipper reports 22.68 °C, which on the
    printer page is just noise. And the house's own entities about a printer carry the printer's
    name ([names] in house.toml): "Klipper summary" is "Voron summary" in a house that calls it
    that, for the dashboard and for Jarvis. Only the name changes, never the entity id"""
    for e in registry():
        for kind, default in (("klipper", "Klipper"), ("bambu", "Bambu")):
            called = NAMES[kind]
            original = e.get("original_name") or ""
            if e["platform"] == "template" and original.startswith(default + " ") \
                    and called.lower() not in (default.lower(), housefile.DEFAULTS["names"][kind].lower()):
                want = called + original[len(default):]
                if e.get("name") != want:
                    update_entity(e["entity_id"], name=want)
    for e in registry():
        eid = e["entity_id"]
        if eid.startswith(("sensor.klipper_", "sensor.bambu_")) and any(k in eid for k in ("temperature", "_temp", "_power", "humidity")) \
                and ((e.get("options") or {}).get("sensor") or {}).get("display_precision") != 0:
            update_entity(eid, options_domain="sensor", options={"display_precision": 0})
    expose(["sensor.bambu_summary", "sensor.bambu_print_progress", "sensor.bambu_remaining_time", "sensor.bambu_end_time",
            "sensor.bambu_nozzle_temperature", "sensor.bambu_bed_temperature", "sensor.bambu_chamber_temperature",
            "light.bambu_chamber_light", "binary_sensor.bambu_hms_errors", "sensor.klipper_summary"])


def step_car():
    """Audi Connect names everything after the car's VIN; packages/car.yaml wants plain car_ names,
    so they're renamed by what they are (the integration's unique ids end in _<platform>_<key>), and
    the few Jarvis can use get shown to him"""
    names = {"sensor_state_of_charge": "sensor.car_battery", "sensor_charging_state": "sensor.car_charging_state",
             "sensor_charging_complete_time": "sensor.car_charging_done_at",
             "sensor_remaining_charging_time": "sensor.car_charging_time_left", "sensor_range": "sensor.car_range",
             "sensor_charging_power": "sensor.car_charging_power", "sensor_target_state_of_charge": "sensor.car_charge_target",
             "binary_sensor_plug_state": "binary_sensor.car_plugged_in", "number_target_state_of_charge": "number.car_charge_target"}
    done = []
    for e in (x for x in registry() if x["platform"] == "audiconnect"):
        key = next((k for k in names if (e.get("unique_id") or "").endswith("_" + k)), None)
        if key:
            rename(e["entity_id"], names[key])
            done.append(names[key])
    if done:
        expose([n for n in done if n.split(".")[1] in ("car_battery", "car_charging_state", "car_charging_done_at",
                                                       "car_range", "car_plugged_in")])
        say(f"car: {len(done)} entities named")


def step_backups():
    """Two apps have to be in the backups or a restore loses things that can't be downloaded again:
    Matter Server holds the pairing for every Matter device, Mosquitto the login the Hub uses"""
    cfg = (ws({"type": "backup/config/info"}) or {}).get("config", {})
    if not cfg:
        return
    have = set(cfg.get("create_backup", {}).get("include_addons") or [])
    want = {"core_matter_server", "core_mosquitto"}
    if not cfg["create_backup"].get("include_all_addons") and not want <= have:
        ws({"type": "backup/config/update", "create_backup": {"include_addons": sorted(have | want)}})
        say("backups now include", ", ".join(sorted(want - have)))


def step_presence():
    """How far you are from home and whether you're getting closer (Proximity), so the house can
    get ready on the way in, and the home zone's size from house.toml"""
    notify = next((d for d in rest("GET", "api/services") or [] if d.get("domain") == "notify"), {})
    if "mobile_app_phone" not in (notify.get("services") or {}):
        say("no notify.mobile_app_phone: name the phone Phone in the companion app before it signs in "
            "(docs/setup.md, step 6). Until then nothing reaches you away from the Hub")
    if "person.resident" not in states():
        say("no person.resident yet: resident.person in house.toml, then run this again")
        return
    if not entries("proximity"):
        r = rest("POST", "api/config/config_entries/flow", {"handler": "proximity", "show_advanced_options": False})
        if r and "flow_id" in r:
            rest("POST", f"api/config/config_entries/flow/{r['flow_id']}",
                 {"zone": "zone.home", "tracked_entities": ["person.resident"], "ignored_zones": [], "tolerance": 50})
            sleep(3)
    # the resident's own sensors, not the "nearest" pair Proximity makes as well
    for e in registry():
        if e["platform"] == "proximity" and "_nearest_" not in e["entity_id"]:
            if e["entity_id"].endswith("_distance") and e["entity_id"].startswith("sensor.home_"):
                rename(e["entity_id"], "sensor.home_resident_distance")
            elif e["entity_id"].endswith("_direction_of_travel"):
                rename(e["entity_id"], "sensor.home_resident_direction_of_travel")
    radius = H["resident"].get("home_radius_m") or 0
    if radius:
        ws({"type": "config/core/update", "radius": int(radius)})


def step_defaults():
    done = set((ssh_ha("cat /config/.ha-hub-defaults 2>/dev/null") or "").split())
    have = states()
    natural = have.get("sensor.natural_house_mode", {}).get("state", "Day")
    todo = DEFAULTS + [("input_select.house_mode", "input_select/select_option", {"option": natural})]
    new = []
    for entity, service, data in todo:
        if entity in done or entity not in have:
            continue
        rest("POST", f"api/services/{service}", {"entity_id": entity, **data})
        new.append(entity)
    if new:
        ssh_ha("cat >> /config/.ha-hub-defaults", ("\n".join(new) + "\n").encode())
        say("starting values:", ", ".join(e.split(".")[1] for e in new))
    # and every run, the settings from house.toml (packages/house.yaml)
    for entity, value in (("input_text.home_wifi", H["resident"]["home_wifi"]), ("input_text.hub_address", H["hub"]["address"]),
                          ("input_text.news", H["news"]["on_arrival"]),
                          ("input_text.interests", H["news"]["interests"]), ("input_text.headset", H["computer"]["headset"]),
                          ("input_text.monitor", H["computer"]["monitor"])):
        if entity in have and have[entity]["state"] != value:
            rest("POST", "api/services/input_text/set_value", {"entity_id": entity, "value": value})


def step_tv_names():
    """The TV everyone sees is media_player.tv (packages/tv.yaml, on top of the ADB one): the room,
    the names people say and the voice. The ADB entities underneath get hidden"""
    reg = {e["entity_id"] for e in registry()}
    if "media_player.fire_tv" in reg:
        update_entity("media_player.fire_tv", name="Fire TV (ADB)", aliases=[], hidden_by="user")
    if "remote.fire_tv_remote" in reg:
        update_entity("remote.fire_tv_remote", name="TV remote", hidden_by="user")
    if "media_player.tv" in reg:
        update_entity("media_player.tv", name="TV", aliases=list(H["fire_tv"]["aliases"]),
                      area_id=areas().get(H["fire_tv"]["area"].lower()))
        expose(["media_player.tv"])


def step_exposure():
    """What the agents can see beyond the devices themselves, and what they can't. Each exposed
    entity makes the prompt a little longer, and some things aren't for voice at all"""
    expose(["weather.forecast_home", "sensor.today_s_weather", "sensor.work_calendar", "sensor.needs_attention",
            "sensor.robot_vacuum_status", "sensor.robot_vacuum_battery", "sensor.robot_vacuum_current_room",
            "script.tv_youtube", "script.tv_netflix", "script.tv_disney_plus", "script.tv_prime_video", "script.tv_spotify",
            "script.tv_ambient", "script.tv_off_completely", "sensor.tv_status",
            "script.movie_night", "script.movie_end", "script.calm_mode", "script.evening_mode", "script.morning_mode",
            "script.day_mode", "script.goodnight", "script.leaving_home", "input_select.house_mode", "input_boolean.guest_mode",
            "sensor.health_trends", "sensor.bedtime_plan", "sensor.usual_wake_time", "sensor.next_wake_up", "sensor.paused",
            "binary_sensor.someone_home", "script.remind_me", "sensor.reminders", "script.vacuum_later", "script.vacuum_clean",
            "timer.vacuum_later", "binary_sensor.washer_running", "sensor.washer_current_status", "sensor.washer_remaining_time",
            "input_datetime.washer_done_at", "input_datetime.doorbell_last_ring", "binary_sensor.at_the_desk",
            "script.computer_lock", "script.computer_say", "button.computer_lock", "button.computer_sleep",
            "button.computer_screen_off", "media_player.computer", "sensor.desk_power"]
           + [f"input_boolean.auto_{x}" for x in ("vacuum", "clock_modes", "welcome", "bedtime_nudge", "asleep", "briefing",
                                                   "security", "doorbell", "laundry", "printers", "desk", "journal")]
           # the ring's main readings, by name: the integration has a contribution, a percentage and a
           # day-on-day change for most of them too, and those only make the prompt longer
           + [f"sensor.oura_ring_{k}" for k in ("sleep_score", "total_sleep_duration", "deep_sleep_duration",
                                                "rem_sleep_duration", "readiness_score", "average_sleep_hrv",
                                                "lowest_sleep_heart_rate", "steps", "activity_score", "bedtime_start",
                                                "bedtime_end")])
    # the control layer's insides and the plumbing: nothing Jarvis needs to read or press
    expose(["sensor.light_arbiter", "sensor.asleep_belief", "binary_sensor.asleep", "sensor.seen_up", "input_text.house_mode_by",
            "input_number.computer_volume_before", "script.wake_up_bedroom_full", "script.wake_up_computer_back",
            "sensor.home_assistant_started", "input_datetime.doorbell_last_lingering", "input_datetime.house_error_at",
            "input_text.house_error_from", "input_datetime.vacuum_asked_at", "input_datetime.wake_up_backstop_at",
            "script.tv_open_app", "script.tv_power", "script.tv_volume", "script.tv_mute", "media_player.fire_tv",
            "remote.fire_tv_remote", "binary_sensor.tv_picture", "binary_sensor.tv_muted", "input_boolean.jarvis_muted",
            "script.lights_look", "script.light_set", "script.house_mode_set", "script.arriving_home", "script.approaching_home",
            "script.welcome_home", "script.welcome_home_prepare", "script.home_wifi_joined", "script.home_wifi_left",
            "timer.arrival_window", "timer.arrival_door", "timer.arrival_greeting", "sensor.natural_house_mode",
            "script.morning_briefing_text", "script.morning_briefing", "script.morning_briefing_prepare", "script.tell_resident",
            "input_text.lights_look", "input_text.home_wifi", "input_text.hub_address", "input_text.news",
            "input_text.interests", "input_text.headset", "input_text.monitor",
            "button.computer_shut_down", "button.computer_restart", "sensor.hub_last_saw_someone", "sensor.last_sign_of_life",
            "script.wake_up", "script.wake_up_stop", "input_boolean.waking_up", "binary_sensor.phone_on_home_wifi"]
           + [e for e in states() if e.startswith(("sensor.phone_", "binary_sensor.phone_")) and "battery" not in e]
           + [e for e in states() if e.startswith("input_datetime.wake_up_")], on=False, keep=H["voice"]["expose"])
    # and whatever the house has chosen to show him on top (voice.expose)
    if H["voice"]["expose"]:
        expose(list(H["voice"]["expose"]))


def step_automations():
    """Every automation in ha/automations/ and in the house's own, keyed by file name (the house's
    wins a name both have)"""
    files = {f.name: f for f in (ROOT / "ha" / "automations").glob("*.json")}
    if housefile.outside():
        files.update({f.name: f for f in (housefile.home() / "ha" / "automations").glob("*.json")})
    for f in (files[k] for k in sorted(files)):
        body = json.loads(f.read_text(encoding="utf-8"))
        if rest("POST", f"api/config/automation/config/{f.stem}", body) is not None:
            say(f"automation {f.stem}")


def step_calendar():
    """The work calendar, as calendar.work, for the busy/free line on the home page. The address
    has the account in it, so it comes from house.toml rather than living in the repo"""
    url = H["calendar"]["work_ics"]
    if url and not any(e["title"] == "Work" for e in entries("remote_calendar")):
        r = flow("remote_calendar", {"calendar_name": "Work", "url": url, "verify_ssl": True})
        say("work calendar:", (r or {}).get("type"))


def step_dashboards():
    """The home dashboard is made from house.toml and what's in Home Assistant (tools/dashboard.py),
    then every dashboard in ha/dashboards/ is saved over whatever's there, so edits belong in the
    generator or the file"""
    out = housefile.build_dir() / "dashboards"
    subprocess.run([sys.executable, str(HERE / "dashboard.py"), "--out", str(out)], check=True, stdout=subprocess.DEVNULL)
    files = {f.name: f for f in (ROOT / "ha" / "dashboards").glob("*.json")}
    files.update({f.name: f for f in out.glob("*.json")})
    if housefile.outside():
        # a dashboard of the house's own, or one in place of the made one
        files.update({f.name: f for f in (housefile.home() / "ha" / "dashboards").glob("*.json")})
    for f in (files[k] for k in sorted(files)):
        url = f.stem
        cfg = json.loads(f.read_text(encoding="utf-8"))
        if not any(d["url_path"] == url for d in ws({"type": "lovelace/dashboards/list"}) or []):
            ws({"type": "lovelace/dashboards/create", "url_path": url, "title": cfg.get("title", url),
                "icon": cfg["views"][0].get("icon", "mdi:view-dashboard"), "show_in_sidebar": True, "require_admin": False})
        ws({"type": "lovelace/config/save", "url_path": url, "config": cfg})
        say(f"dashboard {url}")


def step_fingerprint():
    """Last, because everything above can change it: what the agents' system prompt is built from
    (about.md and about.local.md, the rooms, every exposed entity with its name, aliases and area).
    The satellite keeps one conversation going across wake words for up to 5 minutes, and some
    providers tie a model's reasoning from earlier turns to the exact system prompt it was made
    under: change the prompt mid-conversation and every later request in it fails, and each retry
    keeps the broken conversation alive. Home Assistant has no way to drop one conversation, so
    when the fingerprint changes, it restarts and drops them all"""
    exposed = sorted(k for k, v in ((ws({"type": "homeassistant/expose_entity/list"}) or {}).get("exposed_entities") or {}).items()
                     if v.get("conversation"))
    reg = {e["entity_id"]: e for e in registry()}
    parts = [prompt(), json.dumps(sorted((a["name"], a.get("aliases")) for a in ws({"type": "config/area_registry/list"}) or []))]
    for eid in exposed:
        e = reg.get(eid, {})
        parts.append(json.dumps([eid, e.get("name"), e.get("aliases"), e.get("area_id"), e.get("device_id")]))
    new = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    old = (ssh_ha("cat /config/.ha-hub-prompt-sha 2>/dev/null") or "").strip()
    if new != old:
        ssh_ha(f"echo {new} > /config/.ha-hub-prompt-sha")
        if old and ssh_ha("ha core check >/dev/null && ha core restart >/dev/null && echo ok"):
            say("agent prompt changed, Home Assistant restarted to drop open conversations")


STEPS = [("apps", step_apps), ("discovered", step_discovered), ("local_model", step_local_model),
         ("system_monitor", step_system_monitor), ("tv", step_tv), ("speech", step_speech), ("rooms", step_rooms),
         ("labels", step_labels), ("renames", step_renames), ("lights", step_lights), ("config", step_config), ("journal_log", step_journal_log),
         ("cloud_agent", step_cloud_agent), ("writer", step_writer), ("pipelines", step_pipelines), ("vacuum", step_vacuum),
         ("doorbell", step_doorbell), ("printers", step_printers), ("car", step_car), ("backups", step_backups),
         ("presence", step_presence), ("defaults", step_defaults), ("tv_names", step_tv_names),
         ("exposure", step_exposure), ("automations", step_automations), ("calendar", step_calendar),
         ("dashboards", step_dashboards), ("fingerprint", step_fingerprint)]


def main():
    wanted = [a for a in sys.argv[1:] if a != "--plan"]
    unknown = [w for w in wanted if w not in dict(STEPS)]
    if unknown:
        sys.exit(f"no step called {', '.join(unknown)}. Steps: {', '.join(n for n, _ in STEPS)}")
    if PLAN:
        say(f"plan for {housefile.home()}: nothing below has happened")
    for name, fn in STEPS:
        if not wanted or name in wanted:
            if PLAN:
                say(f"{name}:")
            fn()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
