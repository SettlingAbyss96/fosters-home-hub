"""The house's control core: who gets each light, what a look means right now, the light curve and
the asleep filter (docs/control.md). In Python rather than templates, kept in this repo and loaded
like any other integration, no HACS.

It used to be about 600 lines of Jinja: a light arbiter that kept its memory as JSON in a template
sensor's attributes, a look planner in one long template, and a Bayes filter in a macro. It worked,
but templates made for some odd bugs (`max` turning out to be a built-in, entities coming up as
`_2`), and every light command had to wait up to two seconds for the arbiter to write down what it
was about to ask for. Here the arbiter writes it down and sends the command in the same step.

Nothing else in the house had to change. script.light_set and script.lights_look still exist and
take the same fields, they just call the services below. The entities keep their ids and their
history: sensor.light_arbiter, sensor.asleep_belief and binary_sensor.asleep move over from the
template integration the first time this starts (_move_in). The settings still come from param()
in custom_templates/control.jinja, so there's one table of them, and house.toml's [params] still
fills it in.

Services:
  house_control.light_set   one light, through the gate (what script.light_set does)
  house_control.look        a look, or with dry_run its plan (what script.lights_look does)
Events, so anything can take part, the arbiter included:
  light_commanded  {entity, level, from, fade, source, priority}   what was just asked of a light
  light_hold       {entity, priority, minutes, source}             nothing weaker may change it for a while
  light_release    {entity}                                        let go of it ("all": all but the alarm's)
  light_manual     {entity, state, brightness, by}                 a person changed it ("wall" or "app")
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Context, Event, HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import async_get as restore_state
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .arbiter import Arbiter, real_change
from .curve import bed_and_wake, calm_from, light_curve
from .looks import fraction, level_of, nothing, number, plan

_LOGGER = logging.getLogger(__name__)
DOMAIN = "house_control"

# what moves over from the template integration, keeping its id and history: (domain, unique_id)
MOVED = [("sensor", "light_arbiter"), ("sensor", "asleep_belief"), ("binary_sensor", "asleep")]
# and what this replaces outright: the automation that used to spot a hand at the switch
RETIRED = [("automation", "automation", "light_changed_by_hand")]

# the settings this reads from param() in control.jinja
PARAMS = [
    "priority_manual", "manual_hold_minutes", "command_settle_seconds", "command_match_seconds",
    "command_match_pct", "asleep_on", "asleep_max", "asleep_off", "asleep_hazard_late", "asleep_hazard_evening",
    "asleep_hazard_early", "asleep_hazard_day", "asleep_hazard_max", "asleep_wake_hazard", "asleep_activity_ratio",
    "asleep_typing_ratio", "ambient_level_dark", "ambient_level_daylight", "ambient_level_wind_down",
    "kelvin_morning", "kelvin_evening", "kelvin_floor", "daylight_full_elevation", "wind_down_ramp_minutes",
    "blend_fade_seconds", "blend_ratio", "blend_min_step", "blend_mired_step", "calm_before_bed_minutes",
    "bedtime_without_plan", "wake_without_plan", "stand_in_band", "accent_on_from",
]
LAYER_LABELS = ("light_ambient", "light_task", "light_accent")

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional("looks", default={}): {cv.string: dict}})},
    extra=vol.ALLOW_EXTRA,
)
ANY = vol.Any(None, str, int, float, bool, list, tuple)
LIGHT_SET_SCHEMA = vol.Schema({
    vol.Required("entity"): cv.entity_id,
    **{vol.Optional(k): ANY for k in ("level", "dims", "hs", "kelvin", "fade", "priority", "hold", "source", "override")},
})
LOOK_SCHEMA = vol.Schema({
    vol.Required("look"): ANY,
    **{vol.Optional(k): ANY for k in ("transition", "dry_run", "only_on", "priority", "override", "layers", "blend")},
})


def truthy(v: Any) -> bool:
    """A yes or no the way the templates' | bool read it"""
    if isinstance(v, str):
        return v.strip().lower() in ("true", "on", "yes", "1")
    return bool(v)


def when(v: Any) -> datetime | None:
    """A time from a state or an attribute, local, or None"""
    if isinstance(v, datetime):
        t = v
    elif isinstance(v, str):
        t = dt_util.parse_datetime(v)
        if t is None:
            return None
    else:
        return None
    return dt_util.as_local(t if t.tzinfo else t.replace(tzinfo=dt_util.UTC))


async def _load_params(hass: HomeAssistant) -> dict:
    """param() for every setting this uses, in one render. Numbers come back as numbers"""
    source = "{% from 'control.jinja' import param %}{{ {" + ", ".join(f"'{n}': param('{n}')" for n in PARAMS) + "} | to_json }}"
    raw = Template(source, hass).async_render(parse_result=False)
    out = {}
    for k, v in json.loads(raw).items():
        for kind in (int, float):
            try:
                out[k] = kind(v)
                break
            except (TypeError, ValueError):
                continue
        else:
            out[k] = v
    return out


@callback
def _move_in(hass: HomeAssistant) -> None:
    """The template entities this replaces become this integration's, the same entity under the same
    id, so their history, area and settings carry on. Only ones that haven't loaded can move, which
    is all of them once the template config for them is gone"""
    reg = er.async_get(hass)
    for domain, uid in MOVED:
        if reg.async_get_entity_id(domain, DOMAIN, uid):
            continue
        old = reg.async_get_entity_id(domain, "template", uid)
        if old:
            try:
                # (same unique id, so it isn't passed: Home Assistant takes a "new" one that's already
                # this entry's as taken)
                reg.async_update_entity_platform(old, DOMAIN)
                _LOGGER.info("%s moved over from the template integration", old)
            except ValueError as err:
                _LOGGER.warning("%s couldn't move over from the template integration: %s", old, err)
    for domain, platform, uid in RETIRED:
        if (old := reg.async_get_entity_id(domain, platform, uid)) and hass.states.get(old) is None:
            reg.async_remove(old)
            _LOGGER.info("%s retired: spotting a hand at the switch is this integration's job now", old)


class HouseView:
    """The house as the look planner and the filters see it: states, labels and rooms"""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.ents = er.async_get(hass)
        self.devs = dr.async_get(hass)
        self.labs = lr.async_get(hass)

    def state(self, entity: str) -> str:
        s = self.hass.states.get(entity)
        return s.state if s else "unknown"

    def attr(self, entity: str, name: str, default: Any = None) -> Any:
        s = self.hass.states.get(entity)
        return s.attributes.get(name, default) if s else default

    def tagged(self, label: str) -> list[str]:
        """Every entity with this label, by the label's name or id"""
        lab = self.labs.async_get_label_by_name(label) or self.labs.async_get_label(label)
        return [e.entity_id for e in er.async_entries_for_label(self.ents, lab.label_id)] if lab else []

    def labelled(self, label: str) -> list[str]:
        return [e for e in self.tagged(label) if e.startswith("light.")]

    def labels(self, entity: str) -> set[str]:
        e = self.ents.async_get(entity)
        return set(e.labels) if e else set()

    def area(self, entity: str) -> str | None:
        e = self.ents.async_get(entity)
        if e is None:
            return None
        if e.area_id:
            return e.area_id
        d = self.devs.async_get(e.device_id) if e.device_id else None
        return d.area_id if d else None

    def in_area(self, area: str) -> set[str]:
        out = {e.entity_id for e in er.async_entries_for_area(self.ents, area)}
        for d in dr.async_entries_for_area(self.devs, area):
            out |= {e.entity_id for e in er.async_entries_for_device(self.ents, d.id) if not e.area_id}
        return out

    def runs(self, entity: str) -> bool:
        """One of the house's lights: it has a layer"""
        return bool(self.labels(entity) & set(LAYER_LABELS))

    def is_on(self, entity: str) -> bool:
        return self.state(entity) == "on"


class Core:
    """The arbiter's memory and everything that goes through it"""

    def __init__(self, hass: HomeAssistant, p: dict, looks: dict) -> None:
        self.hass = hass
        self.p = p
        self.looks = {str(k).lower(): v for k, v in looks.items()}
        self.view = HouseView(hass)
        self.arbiter = Arbiter()
        self.ours: dict[str, float] = {}        # contexts our own commands went out with, and when
        self._watchers: list[Callable[[], None]] = []
        self.belief_listeners: list[Callable[[float], None]] = []   # binary_sensor.asleep
        self._flush_pending = False

    # -- time and the record ------------------------------------------------------------------
    @staticmethod
    def now() -> float:
        return dt_util.utcnow().timestamp()

    def watch(self, fn: Callable[[], None]) -> None:
        """fn runs whenever the arbiter's memory changes (sensor.light_arbiter)"""
        self._watchers.append(fn)

    @callback
    def changed(self) -> None:
        """The memory changed: tell the watchers once, however many changes this step made"""
        if self._flush_pending:
            return
        self._flush_pending = True

        def flush() -> None:
            self._flush_pending = False
            for fn in self._watchers:
                fn()

        self.hass.loop.call_soon(flush)

    @callback
    def restore(self) -> None:
        """Holds and commands from before a restart, from the arbiter sensor's last state (the
        template one's, the first time). Anything recorded since startup wins"""
        stored = restore_state(self.hass).last_states.get("sensor.light_arbiter")
        if stored is None:
            return
        attrs = stored.state.attributes
        self.arbiter.holds = {**(attrs.get("holds") or {}), **self.arbiter.holds}
        self.arbiter.commands = {**(attrs.get("commands") or {}), **self.arbiter.commands}
        self.arbiter.prune(self.now())

    @callback
    def tick(self, _now: datetime | None = None) -> None:
        if self.arbiter.prune(self.now()):
            self.changed()
        cutoff = self.now() - 600
        self.ours = {c: t for c, t in self.ours.items() if t > cutoff}

    def held_text(self, h: dict) -> str:
        until = dt_util.as_local(dt_util.utc_from_timestamp(float(h.get("until", 0))))
        return f"held by {h.get('source', '?')} until {until.strftime('%-I:%M %p')}"

    # -- the events ---------------------------------------------------------------------------
    @callback
    def on_commanded(self, event: Event) -> None:
        d = event.data
        if d.get("entity"):
            level = number(d.get("level"))
            self.arbiter.command(d["entity"], level, number(d.get("from", level)), fraction(d.get("fade")),
                                 str(d.get("source", "?")), self.now())
            self.changed()

    @callback
    def on_hold(self, event: Event) -> None:
        d = event.data
        if d.get("entity"):
            self.arbiter.hold(d["entity"], number(d.get("priority"), 4), fraction(d.get("minutes")),
                              str(d.get("source", "?")), self.now())
            self.changed()

    @callback
    def on_release(self, event: Event) -> None:
        if event.data.get("entity"):
            self.arbiter.release(event.data["entity"], self.now())
            self.changed()

    @callback
    def hold(self, entity: str, priority: int, minutes: float, source: str, context: Context) -> None:
        self.arbiter.hold(entity, priority, minutes, source, self.now())
        self.changed()
        self.hass.bus.async_fire("light_hold", {"entity": entity, "priority": priority, "minutes": minutes,
                                                "source": source}, context=context)

    # -- a hand at the switch -----------------------------------------------------------------
    @callback
    def on_state(self, event: Event) -> None:
        """A light changed with nobody's fingerprint on it and nothing the house asked explains it:
        that's a person, at the wall, the dashboard or through Jarvis. The second half matters more
        than it sounds. A Matter light still fading 30 seconds after the command, or an old switch
        answering its next poll, comes back with no fingerprint at all, and would otherwise look
        exactly like someone at the wall (as a sign of life, and as an intruder while you're out)"""
        entity = event.data["entity_id"]
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or old.state not in ("on", "off") or new.state not in ("on", "off"):
            return
        if new.context.parent_id is not None or new.context.id in self.ours or not self.view.runs(entity):
            return
        was_b, b = old.attributes.get("brightness"), new.attributes.get("brightness")
        if not real_change(old.state == "on", was_b, new.state == "on", b):
            return
        p = self.p
        if self.arbiter.explained(entity, new.state == "on", b, self.now(), tolerance_pct=p["command_match_pct"],
                                  settle_seconds=p["command_settle_seconds"], match_seconds=p["command_match_seconds"]):
            return
        ctx = Context(parent_id=new.context.id)
        self.hass.bus.async_fire("light_manual", {
            "entity": entity, "state": new.state, "brightness": int(round(number(b) / 2.55)),
            "by": "app" if new.context.user_id is not None else "wall"}, context=ctx)
        self.hold(entity, p["priority_manual"], p["manual_hold_minutes"], "manual", ctx)

    # -- one light ----------------------------------------------------------------------------
    async def _light(self, service: str, data: dict, context: Context) -> None:
        try:
            await self.hass.services.async_call("light", service, data, blocking=True, context=context)
        except Exception as err:  # noqa: BLE001 - a light that doesn't answer only holds up itself
            _LOGGER.warning("%s didn't take %s: %s", data.get("entity_id"), service, err)

    async def light_set(self, data: dict, context: Context) -> dict:
        """The gate, the record, then the light. A hold from something stronger stops it here; what's
        asked goes on record before the light hears of it, so its answer is never taken for a hand"""
        p, view = self.p, self.view
        entity = data["entity"]
        level = number(data.get("level"))
        pr = 4 if nothing(data.get("priority")) else number(data.get("priority"), 4)
        who = "look" if data.get("source") is None else str(data["source"])
        override = truthy(data.get("override"))
        can_dim = truthy(data["dims"]) if not nothing(data.get("dims")) else any(
            m != "onoff" for m in (view.attr(entity, "supported_color_modes") or []))
        hs = None if nothing(data.get("hs")) else data["hs"]
        kelvin = None if nothing(data.get("kelvin")) else data["kelvin"]
        fade = 2.0 if nothing(data.get("fade")) else fraction(data["fade"])
        # a lamp whose firmware can't fade (light_no_fade) gets everything straight there. A Govee
        # floor lamp asked for 57% to 60% over a minute stays at 57 and wobbles a step either side,
        # so the next blend tick asks again, for as long as the curve wants it higher. Straight
        # there it lands inside a second and sits still, and a blend step is small enough to jump
        if "light_no_fade" in view.labels(entity):
            fade = 0.0
        now = self.now()

        held = self.arbiter.holding(entity, pr, override, now)
        if held is not None:
            return {"done": False, "held": self.held_text(held)}
        # you asking for a mode ends a by-hand hold, so the next clock change can move the light again
        if override and (self.arbiter.holds.get(entity) or {}).get("source") == "manual":
            self.arbiter.release(entity, now)
            self.hass.bus.async_fire("light_release", {"entity": entity}, context=context)
        start = level_of(view, entity)
        self.arbiter.command(entity, level, start, fade, who, now)
        self.ours[context.id] = now
        self.changed()
        self.hass.bus.async_fire("light_commanded", {"entity": entity, "level": level, "from": start, "fade": fade,
                                                     "source": who, "priority": pr}, context=context)

        target = {"entity_id": entity}
        brightness_now = view.attr(entity, "brightness") if view.is_on(entity) and view.attr(entity, "brightness") else 3
        if level == 0:
            await self._light("turn_off", {**target, "transition": fade}, context)
        elif can_dim and (hs is not None or kelvin is not None):
            # Colour and brightness go as two commands, the colour first and straight there, then the
            # brightness with the fade. Both in one command with a fade sent a Govee floor lamp's
            # firmware into a fade that never finished: its Level Control cluster sat at "53.8 s
            # remaining" for hours, reporting its level one step either side of the target 1.4 times
            # a second. The colour command carries the brightness it's already at: a colour on its
            # own makes Home Assistant's Matter light send an On straight after it, and an On a few
            # milliseconds after a colour change can reboot that same lamp. Colour lamps often claim
            # a range far wider than they really do (that Govee says 15 to 6535 K and goes to about
            # 2200), and the floor keeps the light comparable
            colour = ({"hs_color": hs} if hs is not None
                      else {"color_temp_kelvin": min(max(number(kelvin), int(p["kelvin_floor"])), 6500)})
            await self._light("turn_on", {**target, **colour, "brightness": brightness_now, "transition": 0}, context)
            await self._light("turn_on", {**target, "brightness_pct": level, "transition": fade}, context)
        elif can_dim:
            await self._light("turn_on", {**target, "brightness_pct": level, "transition": fade}, context)
        else:
            await self._light("turn_on", target, context)

        hold = fraction(data.get("hold"))
        if hold > 0:
            self.hold(entity, pr, hold, who, context)
        return {"done": True}

    # -- a look -------------------------------------------------------------------------------
    def plan_times(self, now: datetime) -> tuple[datetime, datetime]:
        bed = when(self.view.state("sensor.bedtime_plan"))
        wake = when(self.view.attr("sensor.bedtime_plan", "wake"))
        return bed_and_wake(now, bed, wake, self.p)

    def curve(self) -> dict:
        """The light curve for this minute, and the bedtime it worked from"""
        view, now = self.view, dt_util.now()
        bed, wake = self.plan_times(now)
        hours = view.state("input_number.wind_down_hours")
        c = light_curve(now, fraction(view.attr("sun.sun", "elevation", 0)),
                        _float(view.attr("weather.forecast_home", "cloud_coverage"), 50),
                        _float(hours, 3), bed, wake, self.p)
        return {**c, "bed": bed.isoformat(), "wake": wake.isoformat(), "calm_from": calm_from(bed, self.p).isoformat()}

    async def look(self, data: dict, context: Context) -> dict:
        name = str(data.get("look") or "").lower()
        spec = self.looks.get(name)
        if not spec:
            return {"applied": 0, "why": "no such look"}
        p, view = self.p, self.view
        curve = self.curve()
        # whose colour this look uses: its own, or for the welcome the mode look's (the last one applied)
        borrows = spec.get("colour") == "mode"
        lend = (self.looks.get(view.state("input_text.lights_look")) or {}) if borrows else spec
        k = lend.get("kelvin", "curve" if borrows else None)
        kelvin = curve["kelvin"] if k == "curve" else k
        hs = lend.get("hs")
        blending = truthy(data.get("blend"))
        fade = (fraction(data["transition"]) if not nothing(data.get("transition"))
                else (p["blend_fade_seconds"] if blending else spec.get("transition", 2)))
        pr = 4 if nothing(data.get("priority")) else number(data.get("priority"), 4)
        override = truthy(data.get("override"))
        layers = data.get("layers") or None
        if isinstance(layers, str):
            layers = [layers]
        now = self.now()
        sent = {e: c for e, c in self.arbiter.commands.items()
                if now - float(c.get("at", 0)) >= float(c.get("fade", 0)) + p["command_settle_seconds"]}
        lights = plan(spec, view, curve, p, kelvin=kelvin, hs=hs, blending=blending, only_on=truthy(data.get("only_on")),
                      layers=layers, printing=view.attr("binary_sensor.printing", "lights") or [], sent=sent)

        if truthy(data.get("dry_run")):
            held = {}
            for i in lights:
                if (h := self.arbiter.holding(i["entity"], pr, override, now)) is not None:
                    held[i["entity"]] = self.held_text(h)
            return {"look": data.get("look"), "transition": fade, "plan": lights, "held": held}

        # every light on its own, all at once and not waited on, so one that doesn't answer (a plug
        # whose Matter session dropped can take 39 seconds to give up) only holds up itself. Each
        # one's gate and record happen before this goes on to the next
        no_dim = set(view.labelled("light_no_dim"))
        for i in lights:
            self.hass.async_create_task(self._guarded(self.light_set({
                "entity": i["entity"], "level": i["level"], "dims": i["dims"],
                "hs": hs if i["colour"] else None, "kelvin": i["kelvin"] if i["ct"] else None,
                "fade": 0 if i["entity"] in no_dim else fade, "priority": pr, "override": override,
                "source": f"look {name}"}, context)), eager_start=True)
        if name != "welcome":
            await self.hass.services.async_call("input_text", "set_value",
                                                {"entity_id": "input_text.lights_look", "value": name},
                                                blocking=True, context=context)
        return {"look": data.get("look"), "applied": len(lights)}

    @staticmethod
    async def _guarded(coro) -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001
            _LOGGER.exception("A light command failed")


def _float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    try:
        p = await _load_params(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Couldn't read the settings from param() in custom_templates/control.jinja")
        return False
    looks = (config.get(DOMAIN) or {}).get("looks") or {}
    _move_in(hass)
    core = hass.data[DOMAIN] = Core(hass, p, looks)
    core.restore()

    hass.bus.async_listen("light_commanded", core.on_commanded)
    hass.bus.async_listen("light_hold", core.on_hold)
    hass.bus.async_listen("light_release", core.on_release)
    hass.bus.async_listen(EVENT_STATE_CHANGED, core.on_state,
                          event_filter=callback(lambda d: d["entity_id"].startswith("light.")))
    async_track_time_change(hass, core.tick, second=0)

    async def light_set(call: ServiceCall) -> ServiceResponse:
        return await core.light_set(dict(call.data), call.context)

    async def look(call: ServiceCall) -> ServiceResponse:
        return await core.look(dict(call.data), call.context)

    hass.services.async_register(DOMAIN, "light_set", light_set, LIGHT_SET_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "look", look, LOOK_SCHEMA, SupportsResponse.OPTIONAL)

    for platform in (Platform.SENSOR, Platform.BINARY_SENSOR):
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config), eager_start=True)
    return True

