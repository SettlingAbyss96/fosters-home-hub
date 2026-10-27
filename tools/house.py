#!/usr/bin/env python3
"""house.toml, read once, the same way by everything: the shell scripts through the command line,
tools/setup_ha.py and tools/dashboard.py by importing it. Standard library only (Python 3.11+).

  house.py get KEY [DEFAULT]    one value, dotted (hub.ssh, voice.wake_word). Lists print one a line
  house.py check                 read it, say what's missing or odd, exit 1 on a real problem
  house.py lights                the final light entity ids, one a line
  house.py use PATH              keep your house in its own folder (its own private repo, say)
  house.py where                 the house folder in use
  house.py file NAME             where one of your own files is (about, digest, journal...)

Your house is a folder: house.toml and the few other files that are yours (LOCAL below), laid out
the way they'd sit in this repo, plus anything of your own under ha/config/ that tools/build.py
lays over the packages. It can be this clone itself, with those files gitignored, which is the
quick way to start. The safer way is a folder of its own outside the clone, so nothing of yours is
ever inside it for a git add, a zip or a stray copy to pick up: `house.py use ../my-house`
remembers it in this clone's .git/config, which is never part of a commit. HOUSE_DIR overrides
that for one run, and HOUSE points at a single house.toml (the test bench uses that).
"""
import os
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The files that are yours besides house.toml, where they sit in the house folder (the same place
# they'd sit in a clone). None of them is a secret, but every one of them is about you
LOCAL = {
    "about": "ha/context/about.local.md",           # what Jarvis knows about the household
    "words": "hub/parakeet-words.local.txt",        # the names speech to text should lean towards
    "digest": "hub/digest.toml",                    # what the welcome home reads (hub/digest.example.toml)
    "journal": "hub/journal.toml",                  # what the journal asks about (hub/journal.example.toml)
    "debloat": "tv/debloat.txt",                    # the TV's own debloat list (tv/debloat.example.txt)
    "before": "tv/before.txt",                      # the TV as it was before the debloat
    "private_words": "private-words.txt",           # extra things tools/privacy_check.py stops on
    "config": "ha/config",                          # your own packages, laid over this repo's
}
LAYERS = ("ambient", "task", "accent")
ROLES = ("sunrise", "bedside", "no_dim", "stand_in", "keep")

DEFAULTS = {
    "hub": {"ssh": "hub@ha-hub.local", "address": "", "area": ""},
    "home_assistant": {"url": "http://homeassistant.local", "host": "homeassistant.local"},
    "resident": {"person": "", "face": "", "home_wifi": "", "home_radius_m": 0},
    "voice": {"wake_word": "hey_jarvis", "tts_voice": "bm_daniel", "tts_language": "en_GB",
              "cloud_agent": "", "writer": "", "local_model": "", "address": "", "expose": []},
    "news": {"on_arrival": "", "interests": ""},
    "calendar": {"work_ics": ""},
    "rooms": {"names": [], "aliases": {}},
    "devices": {k: "" for k in ("phone", "computer", "vacuum", "klipper", "bambu", "washer", "doorbell",
                                "front_door", "bedroom_door", "bathroom_door", "desk_power", "phone_notify",
                                "computer_notify")},
    "names": {"klipper": "Klipper printer", "bambu": "Bambu", "vacuum": "vacuum", "computer": "computer", "said": {}},
    "params": {},
    "fire_tv": {"address": "", "area": "", "apps": {}, "aliases": ["television", "telly"], "name": "Fire TV"},
    "klipper": {"moonraker": ""},
    "computer": {"headset": "", "monitor": ""},
    "extras": {"install": ["mushroom"]},
}

# the standard prefix each [devices] entry is renamed to (docs/devices.md)
DEVICE_PREFIX = {"phone": "phone", "computer": "computer", "vacuum": "robot_vacuum", "klipper": "klipper",
                 "bambu": "bambu", "washer": "washer", "doorbell": "doorbell", "front_door": "front_door",
                 "bedroom_door": "bedroom_door", "bathroom_door": "bathroom_door"}


def home() -> pathlib.Path:
    """The house folder: HOUSE_DIR, then the folder `house.py use` remembered, then this clone. A
    remembered folder that's gone is an error rather than a quiet fall back to the clone, which
    would deploy a house that isn't yours or none at all"""
    if os.environ.get("HOUSE_DIR"):
        return pathlib.Path(os.environ["HOUSE_DIR"]).resolve()
    out = subprocess.run(["git", "-C", str(ROOT), "config", "--get", "hub.house"], capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        p = pathlib.Path(out.stdout.strip())
        p = (p if p.is_absolute() else ROOT / p).resolve()
        if not (p / "house.toml").is_file():
            sys.exit(f"this clone's house is {p} (git config hub.house), and there's no house.toml there")
        return p
    return ROOT


def outside() -> bool:
    """Is the house in a folder of its own, rather than in this clone?"""
    return home() != ROOT


def path() -> pathlib.Path:
    return pathlib.Path(os.environ["HOUSE"]) if os.environ.get("HOUSE") else home() / "house.toml"


def file(name: str) -> pathlib.Path:
    """One of your own files (LOCAL), whether or not it's there yet"""
    return home() / LOCAL[name]


def build_dir() -> pathlib.Path:
    """Where tools/build.py puts what goes to Home Assistant. In the house folder, because it's
    full of your house"""
    return home() / ".build"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def load() -> dict:
    p = path()
    if not p.is_file():
        sys.exit(f"no {p}: copy house.example.toml to house.toml and fill it in (docs/setup.md)")
    with open(p, "rb") as f:
        raw = tomllib.load(f)
    house = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for section, values in raw.items():
        if isinstance(values, dict) and isinstance(house.get(section), dict):
            house[section] = {**house[section], **values}
        else:
            house[section] = values
    house["light"] = [light(i, l) for i, l in enumerate(raw.get("light", []))]
    return house


def light(i: int, l: dict) -> dict:
    """One [[light]] table, with its final entity id worked out"""
    entity = l.get("entity", "")
    becomes = l.get("becomes") or (("light." + entity.split(".", 1)[1]) if "." in entity else "")
    return {"entity": entity, "becomes": becomes, "name": l.get("name", ""), "area": l.get("area", ""),
            "layer": l.get("layer", "ambient"), "roles": list(l.get("roles", [])),
            "aliases": list(l.get("aliases", [])), "index": i}


def get(house: dict, key: str, default=None):
    v = house
    for part in key.split("."):
        if not isinstance(v, dict) or part not in v:
            return default
        v = v[part]
    return v


def problems(house: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings): errors stop a deploy, warnings are things you probably meant to fill in"""
    errors, warnings = [], []
    rooms = house["rooms"]["names"]
    room_ids = {slug(r) for r in rooms}
    if not rooms:
        warnings.append("rooms.names is empty: lights and the Hub need rooms to go in")
    for name, where in ((house["hub"]["area"], "hub.area"), (house["fire_tv"]["area"], "fire_tv.area")):
        if name and slug(name) not in room_ids:
            errors.append(f"{where} is {name!r}, which isn't in rooms.names")
    if not house["hub"]["address"]:
        warnings.append("hub.address is empty: Home Assistant can't reach the Hub's speech engines without it")
    if not house["resident"]["person"].startswith("person."):
        warnings.append("resident.person isn't a person entity: presence, the welcome and the wake-up all need one")
    if not house["resident"]["home_wifi"]:
        warnings.append("resident.home_wifi is empty: the phone on the home Wi-Fi won't count as home")
    seen = set()
    for l in house["light"]:
        where = f"light #{l['index'] + 1} ({l['entity'] or 'no entity'})"
        if not re.fullmatch(r"(light|switch)\.[a-z0-9_]+", l["entity"]):
            errors.append(f"{where}: entity should be a light.* or switch.* entity id")
        if not re.fullmatch(r"light\.[a-z0-9_]+", l["becomes"]):
            errors.append(f"{where}: becomes should be a light.* entity id")
        if l["becomes"] in seen:
            errors.append(f"{where}: {l['becomes']} is used twice")
        seen.add(l["becomes"])
        if l["layer"] not in LAYERS:
            errors.append(f"{where}: layer is {l['layer']!r}, it has to be one of {', '.join(LAYERS)}")
        for r in l["roles"]:
            if r not in ROLES:
                errors.append(f"{where}: role {r!r} isn't one of {', '.join(ROLES)}")
        if l["area"] and slug(l["area"]) not in room_ids:
            errors.append(f"{where}: area {l['area']!r} isn't in rooms.names")
    for kind, entity in house["devices"].items():
        if entity and not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", entity):
            errors.append(f"devices.{kind} is {entity!r}, which isn't an entity id")
    for key, start in (("phone_notify", "notify.mobile_app_"), ("computer_notify", "notify.")):
        notify = house["devices"][key]
        if notify and not notify.startswith(start):
            errors.append(f"devices.{key} is {notify!r}: it's a notify service, {start}...")
    for key, value in house["names"].items():
        if key == "said":
            for name, said in value.items():
                if name not in house["names"] or not all(isinstance(s, str) and "|" not in s for s in said):
                    errors.append(f"names.said.{name} should be a list of plain words for one of the names")
        elif not isinstance(value, str) or not re.fullmatch(r"[\w .'+-]+", value):
            errors.append(f"names.{key} is {value!r}: a plain name, letters and spaces")
    if not re.fullmatch(r"[\w .'-]*", house["voice"]["address"]):
        errors.append(f"voice.address is {house['voice']['address']!r}: a plain word or two, like sir")
    if house["calendar"]["work_ics"] and not house["calendar"]["work_ics"].startswith("https://"):
        warnings.append("calendar.work_ics doesn't start with https://")
    return errors, warnings


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "get" and len(args) in (2, 3):
        # a missing house.toml is fine for get with a default: push.sh works before it exists
        if not path().is_file() and len(args) == 3:
            print(args[2])
            return
        v = get(load(), args[1], args[2] if len(args) == 3 else None)
        if v is None:
            sys.exit(f"{args[1]} isn't in {path()}")
        if isinstance(v, list):
            print("\n".join(str(x) for x in v))
        elif isinstance(v, bool):
            print("true" if v else "false")
        else:
            print(v)
    elif args[0] == "check":
        errors, warnings = problems(load())
        for w in warnings:
            print("note:", w)
        for e in errors:
            print("problem:", e)
        if errors:
            sys.exit(1)
        print(f"{path().name} looks right")
    elif args[0] == "lights":
        print("\n".join(l["becomes"] for l in load()["light"]))
    elif args[0] == "use" and len(args) == 2:
        p = pathlib.Path(args[1]).resolve()
        if not (p / "house.toml").is_file():
            sys.exit(f"no house.toml in {p}: copy house.example.toml there first")
        if p == ROOT or ROOT in p.parents:
            sys.exit("the point of a house folder is that it's outside this clone")
        subprocess.run(["git", "-C", str(ROOT), "config", "hub.house", str(p)], check=True)
        print(f"this clone's house is {p} now (git config hub.house)")
    elif args[0] == "where":
        print(home().as_posix())
    elif args[0] == "file" and len(args) == 2 and args[1] in LOCAL:
        print(file(args[1]).as_posix())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
