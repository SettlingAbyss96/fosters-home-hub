"""Looks: how the lights should be for a moment of the day, described by layer instead of by light
(packages/lights.yaml has the looks themselves and what each part of one means, docs/lighting.md
the why). This works out a look's plan: which light gets what, right now.

It reads the house through a View, so a test can hand it a made-up one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

LAYERS = ("ambient", "task", "accent")
COLOUR_MODES = ("hs", "xy", "rgb", "rgbw", "rgbww")
GONE = ("unavailable", "unknown")


class View(Protocol):
    """What the planner needs to know about the house"""

    def state(self, entity: str) -> str: ...                    # "unknown" for one that isn't there
    def attr(self, entity: str, name: str, default: Any = None) -> Any: ...
    def labelled(self, label: str) -> list[str]: ...           # lights only, in a steady order
    def labels(self, entity: str) -> set[str]: ...
    def area(self, entity: str) -> str | None: ...
    def in_area(self, area: str) -> set[str]: ...


def nothing(v: Any) -> bool:
    return v is None or v == "" or v == "None"


def number(v: Any, default: int = 0) -> int:
    """A level as a whole number, the way the templates' | int(0) read one: "curve" and the like
    come out as the default"""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def fraction(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def dims(view: View, entity: str) -> bool:
    return any(m != "onoff" for m in (view.attr(entity, "supported_color_modes") or []))


def level_of(view: View, entity: str) -> int:
    """Where a light is now, in percent, 0 when it's off"""
    if view.state(entity) != "on":
        return 0
    return int(round(number(view.attr(entity, "brightness")) / 2.55))


def scope_of(spec: Mapping, view: View) -> set[str] | None:
    """The areas a look covers, or None for the whole house. "tv" is the TV's room"""
    raw = spec.get("areas")
    if raw is None:
        return None
    tv = view.area("media_player.tv")
    areas = {(tv or "") if a == "tv" else a for a in raw} - {""}
    return areas or None


def plan(spec: Mapping, view: View, curve: Mapping, p: Mapping, *, kelvin: Any, hs: Any, blending: bool,
         only_on: bool, layers: Iterable[str] | None, printing: Iterable[str]) -> list[dict]:
    """[{entity, level, kelvin, dims, ct, colour}], one per light the look changes"""
    scope = scope_of(spec, view)
    no_dim = set(view.labelled("light_no_dim"))
    keep = set(view.labelled("light_keep"))
    printing = set(printing)

    # single lights first, by name and by job, then the layers fill in the rest
    picked: list[dict] = []
    seen: set[str] = set()
    singles = dict(spec.get("entities") or {})
    for role, v in (spec.get("roles") or {}).items():
        for e in view.labelled("light_" + role):
            singles[e] = v
    for e, v in singles.items():
        own = {lab.replace("light_", "") for lab in view.labels(e)}
        layer = next((lay for lay in LAYERS if lay in own), "")
        picked.append({"entity": e, "v": v, "layer": layer})
        seen.add(e)
    for layer, v in (spec.get("layers") or {}).items():
        for e in view.labelled("light_" + layer):
            if e in seen or (scope is not None and view.area(e) not in scope):
                continue
            # an accent light that can't dim is a decoration at full brightness, so a look that
            # wants its accents low (a film) leaves that one off rather than on
            w = v
            if layer == "accent" and isinstance(v, (int, float)) and not dims(view, e) and v < p["accent_on_from"]:
                w = 0
            picked.append({"entity": e, "v": w, "layer": layer})
            seen.add(e)

    # a stand-in takes its room's ambient level, scaled into its own band, when every ambient light
    # in the room is dead (a plug that dropped leaves a glow, not a dark room)
    amb = (spec.get("layers") or {}).get("ambient")
    if amb is not None:
        amb = curve["level"] if amb == "curve" else (amb.get("level") if isinstance(amb, Mapping) else amb)
        top = float(p["stand_in_band"])
        ambient = set(view.labelled("light_ambient"))
        for e in view.labelled("light_stand_in"):
            room = view.area(e)
            if view.state(e) in GONE or not room or (scope is not None and room not in scope):
                continue
            mates = ambient & view.in_area(room)
            if mates and all(view.state(m) in GONE for m in mates):
                lvl = int(round(max(top * fraction(amb) / 100, 1))) if fraction(amb) > 0 else 0
                picked = [i for i in picked if i["entity"] != e] + [{"entity": e, "v": lvl, "layer": "ambient"}]

    wanted = set(layers) if layers else {*LAYERS, ""}
    out = []
    for i in picked:
        e, v = i["entity"], i["v"]
        raw = v.get("level") if isinstance(v, Mapping) else v
        if (view.state(e) in GONE or i["layer"] not in wanted
                or (e in keep and not spec.get("touches_kept"))
                or (e in printing and number(raw) == 0)):
            continue
        level = curve["level"] if raw == "curve" else number(raw)
        if e in no_dim and level > 0:
            level = 100
        # a task light only ever goes on because someone asked: a look can dim it or turn it off
        if_on = (bool(v.get("if_on")) if isinstance(v, Mapping) else False) or (
            i["layer"] == "task" and level > 0 and not spec.get("task_on"))
        if (if_on or only_on) and view.state(e) == "off":
            continue
        modes = list(view.attr(e, "supported_color_modes") or [])
        can_dim = any(m != "onoff" for m in modes)
        ct = "color_temp" in modes
        colour = any(m in COLOUR_MODES for m in modes)
        on = view.state(e) == "on"
        k_want = int(float(kelvin)) if ct and not nothing(kelvin) and nothing(hs) else None
        # keeping lights where they are (the blend ticks): skip what's already there, a plug that's
        # on or a lamp within 30 K and 2% (blending: right on it, or the last step could stop a
        # couple of points short for good)
        now_level = level_of(view, e)
        now_k = number(view.attr(e, "color_temp_kelvin")) if on and view.attr(e, "color_mode") == "color_temp" else 0
        there = on and level > 0 and (not can_dim or (abs(now_level - level) <= (0 if blending else 2)
                                                      and (k_want is None or abs(now_k - k_want) <= 30)))
        if only_on and there:
            continue
        step_level, step_k = level, k_want
        # blending: one step from where the light is, at most 5% of it (2 points at least) and
        # 3 mired of colour, and off once it's down to the last step
        if blending and can_dim and on and now_level > 0 and e not in no_dim:
            step = max(now_level * p["blend_ratio"], p["blend_min_step"])
            s = min(max(level, now_level - step), now_level + step)
            step_level = int(math.ceil(s) if level > now_level else math.floor(s))
            if level == 0 and step_level <= int(p["blend_min_step"]):
                step_level = 0
            if k_want is not None and now_k > 0:
                m_now, m_want, dm = 1e6 / now_k, 1e6 / k_want, p["blend_mired_step"]
                step_k = int(round(1e6 / min(max(m_want, m_now - dm), m_now + dm)))
        out.append({"entity": e, "level": step_level, "kelvin": step_k, "dims": can_dim, "ct": ct, "colour": colour})
    return out
