"""Asleep, one minute of the filter: a two-state hidden Markov model run forward (docs/control.md,
"Estimating asleep").

The clock and the context don't count as evidence each minute, they set the chance of falling
asleep in this minute (the hazard). Evidence that repeats every minute (the phone on the charger,
the house in Night) would otherwise add up minute after minute and get very sure of itself, which is
the naive Bayes trap the first version fell into. The only per-minute evidence is something
happening: a sign of life since the last update is twenty times likelier awake, typing at the
computer a thousand times. "Since the last update" rather than "in the last 60 seconds", so one
landing exactly on a tick, or a late tick, still counts once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .blocks import bayes_step


@dataclass
class Seen:
    """What the house can see this minute"""
    hour: int
    quiet_minutes: float      # since the last sign of life (999 with none)
    active: bool              # a sign of life since the last update
    typing: bool              # at the desk
    home: bool
    night: bool               # the house in Night
    lights_on: bool           # an ambient or task light on
    on_charger: bool
    focus: bool               # the phone's sleep focus or similar
    tv_picture: bool
    bedroom_door_shut: bool
    waking_up: bool


def asleep_next(prev: float, seen: Seen, p: dict) -> dict:
    """prev is the belief a minute ago, 0 to 1. Returns {b, enter, wake, ratio, quiet}: the new
    belief, this minute's hazards and the evidence"""
    h = seen.hour
    if h >= 23 or h < 4:
        base = p["asleep_hazard_late"]
    elif h >= 21:
        base = p["asleep_hazard_evening"]
    elif h < 7:
        base = p["asleep_hazard_early"]
    else:
        base = p["asleep_hazard_day"]
    q = seen.quiet_minutes
    m = ((3 if seen.night else 1)
         * (1 if seen.lights_on else 2)
         * (6 if q >= 45 else (3 if q >= 15 else 1))
         * (1.5 if seen.on_charger else 1)
         * (1.3 if seen.focus else 1)
         * (0.5 if seen.tv_picture else 1)
         * (1.5 if seen.bedroom_door_shut and (h >= 21 or h < 6) else 1))
    enter = 0 if seen.typing else min(base * m, p["asleep_hazard_max"])
    wake = p["asleep_wake_hazard"] * (4 if 5 <= h < 11 else 1) * (5 if seen.waking_up else 1)
    ratio = p["asleep_typing_ratio"] if seen.typing else (p["asleep_activity_ratio"] if seen.active else 1)
    # never surer than 99%: from 99.99 a three-minute trip to the bathroom couldn't pull it back
    b = 0.0001 if not seen.home else min(bayes_step(prev, 1 - wake, enter, ratio), p["asleep_max"])
    return {"b": b, "enter": round(enter, 5), "wake": round(wake, 5), "ratio": ratio, "quiet": int(round(q))}
