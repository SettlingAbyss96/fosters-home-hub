#!/usr/bin/env python3
"""What goes to Home Assistant, built from this repo and your house. Standard library only.

  build.py              into the house folder's .build/config (tools/setup_ha.py deploys from there)
  build.py --bench      the test bench's: no house at all (tools/test.sh)
  build.py --out DIR    somewhere else

ha/config gets copied with your house's words filled in, the lists a state trigger needs spelled
out get made from house.toml, and then your own files under ha/config in the house folder are laid
over the top. The result is plain Home Assistant config, the same as if it had all been written by
hand for your house, so Home Assistant pays nothing for any of this.

The words, written into the packages where Jarvis says them:
  «, sir»       how Jarvis addresses you (voice.address). "sir" stands in for it, and with no address
                the whole thing goes, so "Good night«, sir»." is "Good night." for most houses. A
                sentence that starts with one («Sir, »the print...) gives its capital to the next word
  «a sir|b»     one or the other: a with an address, b without
  «klipper»     what you call a thing (the [names] table): "The «klipper» is printing". A capital in
                the marker («Vacuum») gives the name a capital
  «|klipper»    the other ways speech to text writes that name, each with a | in front, for a custom
                sentence's alternatives: "(klipper|klipper printer«|klipper»)"
And one line: [params] in house.toml replaces `{%- set house = {} -%}` in control.jinja, for the
settings that are really about the house (when a wake-up falls back to without a plan, say).

Anything else between « and » stops the build, so a typo can't end up spoken.
"""
import json
import os
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import house as housefile  # noqa: E402

SOURCE = ROOT / "ha" / "config"
TEXT = (".yaml", ".yml", ".jinja", ".json")
# a marker, and the letter after it (which takes the capital when a sentence-starting «Sir, » goes)
MARKER = re.compile(r"«([^«»\n]*)»(\w?)")
PARAMS_LINE = "{%- set house = {} -%}"


def words(h: dict | None):
    """The function that fills in one marker, for this house (None: the bench, no house)"""
    address = h["voice"]["address"] if h else ""
    names = dict(housefile.DEFAULTS["names"])
    if h:
        names.update(h["names"])
    said = names.pop("said", {}) or {}

    def fill(m: re.Match) -> str:
        inner, after = m.group(1), m.group(2)
        if re.search(r"\b[Ss]ir\b", inner) and "|" in inner.lstrip("|"):
            # «calling them "sir"|calling them by name»: one or the other
            with_it, without = inner.split("|", 1)
            if not address:
                return without + after
            return re.sub(r"\b[Ss]ir\b", lambda w: address[:1].upper() + address[1:] if w.group(0)[0] == "S" else address, with_it) + after
        if re.search(r"\b[Ss]ir\b", inner):
            if not address:
                # «Sir, »the print... started the sentence, so without it "the" does
                return after.upper() if inner[:1] == "S" else after
            return re.sub(r"\b[Ss]ir\b", lambda w: address[:1].upper() + address[1:] if w.group(0)[0] == "S" else address, inner) + after
        if inner.startswith("|") and inner[1:].lower() in names:
            return "".join("|" + s.lower() for s in said.get(inner[1:].lower(), [])) + after
        if inner.lower() in names:
            name = names[inner.lower()]
            return (name[:1].upper() + name[1:] if inner[:1].isupper() else name) + after
        raise ValueError(f"«{inner}» isn't a marker build.py knows")
    return fill


def render(text: str, h: dict | None) -> str:
    """One text with this house's words in (None: the bench's, no house)"""
    return MARKER.sub(words(h), text)


def lists(h: dict) -> dict[str, str]:
    """ha/config/house/: the lists a state trigger needs spelled out (packages/lights.yaml's
    triggers can't follow a label)"""
    lights = [l["becomes"] for l in h["light"]]
    no_dim = [l["becomes"] for l in h["light"] if "no_dim" in l["roles"]]
    # a state trigger needs at least one entity; one that never exists never fires
    return {name: "# made by tools/build.py from house.toml\n" + ("".join(f"- {i}\n" for i in ids) or "- light.none_in_house_toml\n")
            for name, ids in (("house/lights.yaml", lights), ("house/no_dim_lights.yaml", no_dim))}


def notifiers(h: dict) -> dict[str, str]:
    """The packages tell you things through notify.mobile_app_phone and notify.computer. A phone
    that signed in under another name, or a computer HASS.Agent knows by another, gets the standard
    name too, as a group of one, since neither integration can rename its own service"""
    groups = [(want, h["devices"].get(key, "")) for key, want in (("phone_notify", "mobile_app_phone"),
                                                                    ("computer_notify", "computer"))]
    groups = [(want, have.split(".", 1)[1]) for want, have in groups if have and have != f"notify.{want}"]
    if not groups:
        return {}
    body = "".join(f"  - platform: group\n    name: {want}\n    services:\n      - action: {have}\n" for want, have in groups)
    return {"packages/house_notify.yaml": "# made by tools/build.py from [devices] in house.toml: notify services under the\n"
                                          "# names the packages use\nnotify:\n" + body}


def params(text: str, h: dict) -> str:
    """control.jinja with the house's own settings in"""
    mine = h.get("params") or {}
    if not mine:
        return text
    known = set(re.findall(r"^\s*'([a-z_]+)':", text, re.M))
    unknown = sorted(set(mine) - known)
    if unknown:
        raise ValueError(f"[params] in house.toml has {', '.join(unknown)}, which control.jinja doesn't")
    if text.count(PARAMS_LINE) != 1:
        raise ValueError(f"control.jinja should have `{PARAMS_LINE}` once, for [params]")
    return text.replace(PARAMS_LINE, "{%- set house = " + json.dumps(mine, sort_keys=True) + " -%}")


def build(out: pathlib.Path, h: dict | None) -> list[str]:
    """Write the config into out (emptied first). Returns notes worth showing"""
    notes = []
    fill = words(h)
    if out.exists():
        shutil.rmtree(out)
    for p in sorted(SOURCE.rglob("*")):
        if not p.is_file() or p.relative_to(SOURCE).parts[0] == "house" or "__pycache__" in p.parts:
            continue
        dest = out / p.relative_to(SOURCE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix in TEXT:
            text = p.read_text(encoding="utf-8")
            try:
                text = MARKER.sub(fill, text)
            except ValueError as e:
                raise ValueError(f"{p.relative_to(ROOT)}: {e}") from None
            if h is not None and p.name == "control.jinja":
                text = params(text, h)
            dest.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(p, dest)
    if h is None:
        return notes
    for rel, text in {**lists(h), **notifiers(h)}.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8", newline="\n")
    mine = housefile.file("config")
    if housefile.outside() and mine.is_dir():
        for p in sorted(mine.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(mine)
            dest = out / rel
            if dest.exists():
                notes.append(f"your {rel.as_posix()} replaces this repo's")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
    return notes


def main():
    args = sys.argv[1:]
    bench = "--bench" in args
    out = pathlib.Path(args[args.index("--out") + 1]).resolve() if "--out" in args else None
    if bench:
        h = None
        out = out or ROOT / ".tmp-bench" / "config"
    else:
        h = housefile.load()
        out = out or housefile.build_dir() / "config"
    try:
        notes = build(out, h)
    except ValueError as e:
        sys.exit(f"build: {e}")
    for n in notes:
        print("note:", n)
    print(out)


if __name__ == "__main__":
    main()
