"""Who gets the light (docs/control.md, "Who gets the light"). Plain Python, no Home Assistant, so
the tests can drive it with any clock.

Every light command in the house goes through the gate with a priority, lower wins:
    1 the alarm and safety, 2 a person by hand (and the fell-asleep check), 3 routines,
    4 the mode's look, 5 background
A command can leave a hold on a light: for so many minutes, nothing weaker may change it. The alarm
holds the sunrise lights for the morning, and a light switched by hand is held for three hours, so
the clock moving the house to Evening doesn't undo it. Picking a mode yourself goes past holds from a
hand at the switch and below (the override), never past the alarm's.

The arbiter also remembers what it last asked of each light, so a light reporting back isn't taken
for a person at the switch. It used to be a template sensor folding events into its own
attributes, which runs as a task: every command had to wait up to two seconds for its own record
before going out, or the light's answer could beat it there and look exactly like a hand. Here the
record is written before the command is sent, in the same step, so there's nothing to wait for.
"""

from __future__ import annotations

OVERRIDE_PASSES_FROM = 2       # you asking for a mode passes holds of priority 2 (by hand) and weaker
COMMAND_MEMORY_SECONDS = 600   # what was asked of a light is forgotten after ten minutes


class Arbiter:
    """The holds and the command memory, keyed by light. A hold is {priority, until, source} with
    until in epoch seconds, a command {level, fade, from, at, source}"""

    def __init__(self, holds: dict | None = None, commands: dict | None = None) -> None:
        self.holds: dict[str, dict] = dict(holds or {})
        self.commands: dict[str, dict] = dict(commands or {})

    # -- the memory ---------------------------------------------------------------------------
    def prune(self, now: float) -> bool:
        """Expired holds and old commands drop out. True if anything did"""
        before = (len(self.holds), len(self.commands))
        self.holds = {e: h for e, h in self.holds.items() if float(h.get("until", 0)) > now}
        self.commands = {e: c for e, c in self.commands.items() if now - float(c.get("at", 0)) < COMMAND_MEMORY_SECONDS}
        return before != (len(self.holds), len(self.commands))

    def hold(self, entity: str, priority: int, minutes: float, source: str, now: float) -> None:
        self.prune(now)
        self.holds[entity] = {"priority": int(priority), "until": round(now + minutes * 60, 0), "source": source}

    def release(self, entity: str, now: float) -> None:
        """Let go of a light, or with "all" of everything but the alarm's"""
        self.prune(now)
        if entity == "all":
            self.holds = {e: h for e, h in self.holds.items() if int(h.get("priority", 9)) <= 1}
        else:
            self.holds.pop(entity, None)

    def command(self, entity: str, level: int, start: int, fade: float, source: str, now: float) -> None:
        self.prune(now)
        self.commands[entity] = {"level": int(level), "fade": float(fade), "from": int(start),
                                 "at": round(now, 1), "source": source}

    # -- the gate -----------------------------------------------------------------------------
    def holding(self, entity: str, priority: int, override: bool, now: float) -> dict | None:
        """The hold that stops a request of this priority changing this light now, or None to go.
        Equal or weaker holds let it through (the newest wins: the alarm's next sunrise step past its
        own last one, the fell-asleep check past a hand at the switch)"""
        h = self.holds.get(entity)
        if h is None or float(h.get("until", 0)) <= now:
            return None
        held_at = int(h.get("priority", 9))
        if held_at >= priority:
            return None
        if override and held_at >= OVERRIDE_PASSES_FROM:
            return None
        return h

    # -- by hand ------------------------------------------------------------------------------
    def explained(self, entity: str, on: bool, brightness: int | None, now: float, *,
                  tolerance_pct: float, settle_seconds: float, match_seconds: float) -> bool:
        """Whether a change with no automation's fingerprint on it is just the light reporting back
        what the house asked for: inside the fade plus a few seconds, somewhere on the way from where
        it was to where it was asked to go, or inside two minutes once it's settled, about the level
        asked for. "On the way" matters because of the blending: with a fade running nearly every
        minute, "anything goes during a fade" would stop the house ever seeing a hand on a dimmer.
        From off there's no knowing the way: a light switched on comes up at whatever it had last,
        then fades. brightness is 0 to 255, None for a light that doesn't say"""
        c = self.commands.get(entity)
        if c is None:
            return False
        since = now - float(c.get("at", 0))
        asked = int(c.get("level", 0))
        start = int(c.get("from", asked))
        want_on = asked > 0
        level = round((brightness if brightness is not None else 255) / 2.55)
        on_the_way = brightness is None or start == 0 or min(start, asked) - tolerance_pct <= level <= max(start, asked) + tolerance_pct
        fading = (on and on_the_way) or (not on and not want_on)
        same_state = on == want_on
        same_level = not want_on or brightness is None or abs(level - asked) <= tolerance_pct
        return ((fading and since < float(c.get("fade", 0)) + settle_seconds)
                or (same_state and same_level and since < match_seconds))


def real_change(was_on: bool, was_brightness: int | None, on: bool, brightness: int | None) -> bool:
    """On to off or back, or more than 8 of 255 in brightness. A colour lamp also reports its colour
    and effect all the time, and a lamp whose firmware never finishes a fade can report 202, 203, 202
    a few times a second, and none of that is a person"""
    return was_on != on or abs((was_brightness or 0) - (brightness or 0)) > 8
