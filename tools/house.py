#!/usr/bin/env python3
"""house.toml, read once, the same way by everything: the shell scripts through the command line,
tools/setup_ha.py and tools/dashboard.py by importing it. Standard library only (Python 3.11+).

  house.py get KEY [DEFAULT]    one value, dotted (hub.ssh, voice.wake_word). Lists print one a line
  house.py check                 read it, say what's missing or odd, exit 1 on a real problem
  house.py lights                the final light entity ids, one a line

house.toml lives next to this repo's README and never goes in git (house.example.toml is the one
that does). HOUSE overrides the path, for the test bench and for running two houses from one clone.
"""
import os
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAYERS = ("ambient", "task", "accent")
ROLES = ("sunrise", "bedside", "no_dim", "stand_in", "keep")

DEFAULTS = {
    "hub": {"ssh": "hub@ha-hub.local", "address": "", "area": ""},
    "home_assistant": {"url": "http://homeassistant.local", "host": "homeassistant.local"},
    "resident": {"person": "", "face": "", "home_wifi": "", "home_radius_m": 0},
    "voice": {"wake_word": "hey_jarvis", "tts_voice": "bm_daniel", "tts_language": "en_GB",
              "cloud_agent": "", "local_model": ""},
    "news": {"on_arrival": "", "interests": ""},
    "calendar": {"work_ics": ""},
    "rooms": {"names": [], "aliases": {}},
    "devices": {k: "" for k in ("phone", "computer", "vacuum", "klipper", "bambu", "washer", "doorbell",
                                "front_door", "bedroom_door", "bathroom_door", "desk_power")},
    "fire_tv": {"address": "", "area": "", "apps": {}},
    "klipper": {"moonraker": ""},
    "computer": {"headset": ""},
    "extras": {"install": ["mushroom"]},
}

# the standard prefix each [devices] entry is renamed to (docs/devices.md)
DEVICE_PREFIX = {"phone": "phone", "computer": "computer", "vacuum": "robot_vacuum", "klipper": "klipper",
                 "bambu": "bambu", "washer": "washer", "doorbell": "doorbell", "front_door": "front_door",
                 "bedroom_door": "bedroom_door", "bathroom_door": "bathroom_door"}


def path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("HOUSE", ROOT / "house.toml"))


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
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
