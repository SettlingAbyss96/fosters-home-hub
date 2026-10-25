"""The house on the test bench: the real packages in a real Home Assistant, a fake set of lights,
every other service recorded instead of called, and a clock that only moves when a test says so.

    house = await House.build(hass, freezer, "2026-10-13 04:50")
    house.set("binary_sensor.hub_500_motion", "on")
    await house.advance(minutes=30)
    assert house.said("Good morning")

Lights are fakes that behave like the real ones: a command changes the state with the command's
context (like a Matter light answering inside a second), a person changing one doesn't carry any
(house.by_hand), and house.dead marks a light that errors on every command.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from datetime import datetime, timedelta

from homeassistant import config as conf_util
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_HS_COLOR, ColorMode, LightEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.template import async_load_custom_templates
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import (
    MockModule,
    MockPlatform,
    async_fire_time_changed,
    mock_integration,
    mock_platform,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFIG = REPO / "ha" / "config"
TZ = "America/New_York"

# what gets set up for real. Everything else the packages call is recorded
DOMAINS = ["input_boolean", "input_datetime", "input_number", "input_select", "input_text", "timer",
           "template", "script", "automation", "intent_script"]

# The bench's made-up home: a colour floor lamp and a strip in the living room, a kitchen ceiling
# whose bulbs can't dim, a bathroom light on the fan's switch, a bedroom with a dimmable overhead (the
# sunrise) and a plug lamp by the bed, and two printers' lights in the hall.
# light, area, layer, dims, colour, jobs (the other light_ labels, packages/lights.yaml)
LIGHTS = [
    ("light.living_room_lamp", "living_room", "ambient", True, True, []),
    ("light.living_room_ambient", "living_room", "ambient", False, False, []),
    ("light.kitchen_light", "kitchen", "task", True, False, ["no_dim"]),
    ("light.bathroom_light", "bathroom", "task", False, False, ["keep"]),
    ("light.bedroom_light", "bedroom", "task", True, False, ["sunrise", "stand_in"]),
    ("light.bedroom_lamp", "bedroom", "ambient", False, False, ["bedside"]),
    ("light.klipper_case_light", "hall", "accent", True, False, []),
    ("light.bambu_chamber_light", "hall", "accent", False, False, []),
]
AREAS = ["Living Room", "Kitchen", "Bathroom", "Bedroom", "Hall"]
DOORS = {"binary_sensor.bedroom_door": "bedroom", "binary_sensor.bathroom_door": "bathroom"}
LABELS = ["light_ambient", "light_task", "light_accent", "light_sunrise", "light_bedside", "light_no_dim",
          "light_stand_in", "light_keep", "room_door", "vacuum_room"]
HOME_WIFI = "HomeNet"

# The bench household's own routine, set after the deploy's neutral starting values: an early
# start (settled at work by 7:00, 40 minutes away, 45 minutes of morning, 10 early), so a workday's
# wake time is 5:25 and the tests can name the minutes. Made up, and fixed here so a change to the
# starting values in tools/setup_ha.py doesn't move every test
ROUTINE = [
    ("input_datetime.work_arrival", "input_datetime/set_datetime", {"time": "07:00:00"}),
    ("input_number.commute_minutes", "input_number/set_value", {"value": 40}),
    ("input_number.sleep_goal", "input_number/set_value", {"value": 7.5}),
    ("input_text.home_wifi", "input_text/set_value", {"value": HOME_WIFI}),
    ("input_text.news", "input_text/set_value", {"value": "the day's top story and how the markets did"}),
    ("input_text.interests", "input_text/set_value", {"value": "cooking, cycling"}),
]

BASELINE = {
    "person.resident": ("home", {"friendly_name": "Sam"}),
    "sensor.phone_ssid": HOME_WIFI,
    "conversation.jarvis_cloud": "unknown",
    "sun.sun": ("below_horizon", {"elevation": -20}),
    "binary_sensor.hub_500_motion": "off",
    "binary_sensor.tv_picture": "off",
    "sensor.tv_status": "Off",
    "sensor.computer_session_state": "Locked",
    "sensor.computer_last_active": "2026-01-01T00:00:00+00:00",
    "binary_sensor.phone_focus": "off",
    "vacuum.robot_vacuum": "docked",
    "media_player.hub_500_voice_media_player": ("idle", {"volume_level": 0.66}),
    "media_player.computer": ("idle", {"volume_level": 0.3}),
    "assist_satellite.hub_500_voice_assist_satellite": "idle",
}


class BenchLight(LightEntity):
    """A light that behaves like the real ones: a command lands with the command's context, and
    the house can change it "by hand" or have it "report back" with no context at all"""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, house: "House", entity_id: str, dims: bool, colour: bool) -> None:
        self._house = house
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self._attr_name = entity_id.split(".")[1].replace("_", " ")
        if colour:
            self._attr_supported_color_modes = {ColorMode.HS, ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.HS
            self._attr_hs_color = (30, 50)
            self._attr_min_color_temp_kelvin, self._attr_max_color_temp_kelvin = 2200, 6500
        elif dims:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
        self._dims = dims or colour
        self._attr_is_on = False
        self._attr_brightness = None

    async def async_turn_on(self, **kwargs) -> None:
        self._house.light_calls.append((self.entity_id, "on", kwargs))
        if self.entity_id in self._house.dead:
            raise HomeAssistantError(f"{self.entity_id} didn't answer")
        self._attr_is_on = True
        if self._dims:
            self._attr_brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
        # a colour light keeps the last colour it was given, like the Govee: on with only a
        # brightness comes back at whatever it had
        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._attr_supported_color_modes and ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
            self._attr_color_mode, self._attr_color_temp_kelvin = ColorMode.COLOR_TEMP, kwargs[ATTR_COLOR_TEMP_KELVIN]
        if ATTR_HS_COLOR in kwargs and self._attr_supported_color_modes and ColorMode.HS in self._attr_supported_color_modes:
            self._attr_color_mode, self._attr_hs_color = ColorMode.HS, kwargs[ATTR_HS_COLOR]
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._house.light_calls.append((self.entity_id, "off", kwargs))
        if self.entity_id in self._house.dead:
            raise HomeAssistantError(f"{self.entity_id} didn't answer")
        self._attr_is_on = False
        self.async_write_ha_state()

    def change(self, on: bool, brightness_pct: int | None, context: Context, kelvin: int | None = None) -> None:
        self._attr_is_on = on
        if self._dims and on:
            self._attr_brightness = round(brightness_pct * 2.55) if brightness_pct else (self._attr_brightness or 255)
        if kelvin is not None:
            self._attr_color_mode, self._attr_color_temp_kelvin = ColorMode.COLOR_TEMP, kelvin
        self.async_set_context(context)
        self.async_write_ha_state()


def defaults_from_deploy_script() -> list[tuple[str, str, dict]]:
    """The starting values tools/setup_ha.py gives the helpers, read out of it so there's one list
    (not imported: setup_ha.py reads house.toml the moment it loads)"""
    text = (REPO / "tools" / "setup_ha.py").read_text(encoding="utf-8")
    block = text[text.index("DEFAULTS = ["):]
    block = block[: block.index("\n]") + 2]
    scope: dict = {"natural": "Day"}
    exec(block, scope)  # noqa: S102 - our own file, a list of tuples
    return scope["DEFAULTS"]


class House:
    def __init__(self, hass: HomeAssistant, freezer) -> None:
        self.hass = hass
        self.freezer = freezer
        self.calls: list[ServiceCall] = []
        self.light_calls: list = []
        self.lights: dict[str, BenchLight] = {}
        self.events: list = []
        self.dead: set[str] = set()
        # what a faked service answers, by "domain.service": the cloud agent's words, say
        self.replies: dict[str, dict] = {}

    # -- building ---------------------------------------------------------------------------------
    @classmethod
    async def build(cls, hass: HomeAssistant, freezer, at: str, states: dict | None = None) -> "House":
        house = cls(hass, freezer)
        await hass.config.async_set_time_zone(TZ)
        start = dt_util.as_utc(datetime.fromisoformat(at).replace(tzinfo=dt_util.get_time_zone(TZ)))
        # the furniture goes in a day early: in a real house the vacuum docked and the lights went
        # off hours ago, not the instant the test began
        freezer.move_to(start - timedelta(days=1))

        house._lists()
        templates = pathlib.Path(hass.config.config_dir) / "custom_templates"
        templates.mkdir(parents=True, exist_ok=True)
        for f in (CONFIG / "custom_templates").glob("*.jinja"):
            (templates / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        await async_load_custom_templates(hass)

        await house._registries()
        await house._lights()
        house._baseline(states or {})
        house._fake_services()
        freezer.move_to(start)

        # only the parts the bench sets up (voice_debug's assist_pipeline would need the whole voice stack)
        packages = {p.stem: {k: v for k, v in load_yaml_dict(p).items() if k in DOMAINS}
                    for p in sorted((CONFIG / "packages").glob("*.yaml"))}
        config = await conf_util.merge_packages_config(hass, {"homeassistant": {}}, packages)
        for domain in DOMAINS:
            assert await async_setup_component(hass, domain, config), f"{domain} didn't set up"
        await hass.async_block_till_done()

        # a lived-in house: every date-and-time helper starts long ago, the way a real one has been
        # set some day before today (a brand new one says midnight today, which reads as "already
        # happened today")
        for st in hass.states.async_all("input_datetime"):
            if st.attributes.get("has_date") and st.attributes.get("has_time"):
                await hass.services.async_call("input_datetime", "set_datetime",
                                               {"entity_id": st.entity_id, "datetime": "2000-01-01 00:00:00"}, blocking=True)
        for entity, service, data in defaults_from_deploy_script() + ROUTINE:
            domain, name = service.split("/")
            if hass.states.get(entity) is not None and hass.services.has_service(domain, name):
                await hass.services.async_call(domain, name, {"entity_id": entity, **data}, blocking=True)
        for entity, value in (states or {}).items():
            house.set(entity, value)
        await house.settle()
        hass.bus.async_listen("light_manual", lambda e: house.events.append(("light_manual", dict(e.data))))
        hass.bus.async_listen("light_hold", lambda e: house.events.append(("light_hold", dict(e.data))))
        return house

    @staticmethod
    def _lists() -> None:
        """ha/config/house/, the way tools/setup_ha.py writes it from house.toml, for the bench's lights"""
        out = CONFIG / "house"
        out.mkdir(parents=True, exist_ok=True)
        (out / "lights.yaml").write_text("".join(f"- {l[0]}\n" for l in LIGHTS), encoding="utf-8")
        (out / "no_dim_lights.yaml").write_text("".join(f"- {l[0]}\n" for l in LIGHTS if "no_dim" in l[5]), encoding="utf-8")

    async def _registries(self) -> None:
        labels = lr.async_get(self.hass)
        for label in LABELS:
            if labels.async_get_label_by_name(label) is None:
                labels.async_create(label)
        areas = ar.async_get(self.hass)
        for name in AREAS:
            if areas.async_get_area_by_name(name) is None:
                areas.async_create(name)
            # the vacuum knows every room on the bench (tools/setup_ha.py labels the ones it does)
            a = areas.async_get_area_by_name(name)
            areas.async_update(a.id, labels={"vacuum_room"})
        ents = er.async_get(self.hass)
        for entity, area, layer, _dims, _colour, jobs in LIGHTS:
            e = ents.async_get_or_create("light", "bench", entity, suggested_object_id=entity.split(".")[1])
            ents.async_update_entity(e.entity_id, area_id=area, labels={f"light_{layer}"} | {f"light_{j}" for j in jobs})
        for entity, area in DOORS.items():
            e = ents.async_get_or_create("binary_sensor", "bench", entity, suggested_object_id=entity.split(".")[1])
            ents.async_update_entity(e.entity_id, area_id=area, labels={"room_door"})

    async def _lights(self) -> None:
        mock_integration(self.hass, MockModule("bench"))
        self.lights = {e: BenchLight(self, e, dims, colour) for e, _a, _r, dims, colour, _j in LIGHTS}

        async def setup_platform(hass, config, add_entities, discovery_info=None):
            add_entities(list(self.lights.values()))

        mock_platform(self.hass, "bench.light", MockPlatform(async_setup_platform=setup_platform))
        assert await async_setup_component(self.hass, "light", {"light": [{"platform": "bench"}]})
        await self.hass.async_block_till_done()

    def _baseline(self, overrides: dict) -> None:
        for entity, value in BASELINE.items():
            if entity not in overrides:
                self.set(entity, value)

    def _fake_services(self) -> None:
        hass = self.hass

        @callback
        def record(call: ServiceCall):
            self.calls.append(call)
            return self.replies.get(f"{call.domain}.{call.service}", {})

        text = "\n".join(p.read_text(encoding="utf-8") for p in (CONFIG / "packages").glob("*.yaml"))
        wanted = set(re.findall(r"action: ([a-z_]+)\.([a-z_0-9]+)\s*$", text, re.M))
        for domain, name in wanted:
            if domain in DOMAINS or domain in ("light", "script", "automation") or hass.services.has_service(domain, name):
                continue
            hass.services.async_register(domain, name, record, supports_response=SupportsResponse.OPTIONAL)

    # -- the world --------------------------------------------------------------------------------
    def set(self, entity: str, value, **attrs) -> None:
        if isinstance(value, tuple):
            value, more = value
            attrs = {**more, **attrs}
        old = self.hass.states.get(entity)
        merged = {**(dict(old.attributes) if old else {}), **attrs}
        self.hass.states.async_set(entity, value, merged)

    def by_hand(self, entity: str, state: str, brightness_pct: int | None = None, app: bool = False) -> None:
        """A person at the wall (or the dashboard, with app=True): no automation behind it"""
        self.lights[entity].change(state == STATE_ON, brightness_pct, Context(user_id="resident") if app else Context())

    def report(self, entity: str, state: str, brightness_pct: int | None = None, kelvin: int | None = None) -> None:
        """A light reporting back on its own, no context at all (a late Matter update, a Kasa poll, a
        lamp back from a restart at its own default colour)"""
        self.lights[entity].change(state == STATE_ON, brightness_pct, Context(), kelvin)

    def is_on(self, entity: str) -> bool:
        return self.hass.states.is_state(entity, STATE_ON)

    def level(self, entity: str) -> int:
        b = self.hass.states.get(entity).attributes.get("brightness")
        return round(b / 2.55) if b is not None else (100 if self.is_on(entity) else 0)

    def state(self, entity: str) -> str:
        s = self.hass.states.get(entity)
        return s.state if s else "missing"

    def attr(self, entity: str, name: str):
        s = self.hass.states.get(entity)
        return s.attributes.get(name) if s else None

    # -- time -------------------------------------------------------------------------------------
    async def settle(self, rounds: int = 200) -> None:
        """Let everything that can run, run. Not hass.async_block_till_done: that waits for every
        script to finish, and the wake-up sits in a one-minute delay that only the next tick of the
        frozen clock lets go of, so it would wait forever"""
        for _ in range(rounds):
            await asyncio.sleep(0)

    async def advance(self, minutes: float = 0, seconds: float = 0, step: float = 30) -> None:
        total = minutes * 60 + seconds
        while total > 0:
            d = min(step, total)
            self.freezer.tick(timedelta(seconds=d))
            async_fire_time_changed(self.hass, dt_util.utcnow())
            await self.settle()
            total -= d

    def now(self) -> datetime:
        return dt_util.now()

    # -- what happened ----------------------------------------------------------------------------
    def called(self, service: str, **match) -> list[ServiceCall]:
        domain, name = service.split(".", 1)
        out = []
        for c in self.calls:
            if c.domain == domain and c.service == name and all(
                str(m) in str(c.data.get(k, "")) for k, m in match.items()
            ):
                out.append(c)
        return out

    def said(self, words: str) -> bool:
        return any(words in str(c.data.get("message", "")) for c in self.called("assist_satellite.announce"))

    def phoned(self, words: str = "") -> list[ServiceCall]:
        return [c for c in self.called("notify.mobile_app_phone") if words in str(c.data)]

    def forget(self) -> None:
        self.calls.clear()
        self.events.clear()

    async def run(self, script: str, **data) -> None:
        await self.hass.services.async_call("script", script, data, blocking=True)
        await self.settle()

    async def ask(self, intent_name: str, **slots) -> str:
        """An intent the way a sentence reaches it ("what's my morning brief" is MorningBriefing),
        and what Jarvis says back"""
        from homeassistant.helpers import intent

        task = self.hass.async_create_task(intent.async_handle(
            self.hass, "bench", intent_name, {k: {"value": v} for k, v in slots.items()}))
        for _ in range(60):                        # the intent's own waits run on the frozen clock
            if task.done():
                break
            await self.advance(seconds=1, step=1)
        response = await task
        await self.settle()
        return response.speech.get("plain", {}).get("speech", "")
