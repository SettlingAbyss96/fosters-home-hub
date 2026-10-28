"""The control core's sensors:
  sensor.light_arbiter   how many lights are held, with the holds and the last command to each light
                         as attributes (what the dashboard and a few automations read)
  sensor.asleep_belief   how sure the house is you're asleep, 0 to 100, one filter step a minute
  sensor.light_curve     the light curve's level for now, with its colour and tonight's bedtime, wake
                         time and when Calm starts
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN, LAYER_LABELS, Core, when
from .asleep import Seen, asleep_next


async def async_setup_platform(hass: HomeAssistant, config: Any, add: AddEntitiesCallback,
                               discovery_info: Any = None) -> None:
    core: Core = hass.data[DOMAIN]
    add([ArbiterSensor(core), AsleepBelief(core), LightCurve(core)])


class _Base(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, core: Core, uid: str, name: str, icon: str) -> None:
        self.core = core
        self._attr_unique_id = uid
        self._attr_name = name
        self._attr_icon = icon
        self.entity_id = f"sensor.{uid}"


class ArbiterSensor(_Base, RestoreEntity):
    """What the arbiter holds and remembers. The memory itself is the core's (it reads this one's
    last state back at startup); this is how the rest of the house sees it"""

    def __init__(self, core: Core) -> None:
        super().__init__(core, "light_arbiter", "Light arbiter", "mdi:traffic-light-outline")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.core.watch(self._changed)
        self._changed()

    @callback
    def _changed(self) -> None:
        if self.hass is None:
            return
        self._attr_native_value = len(self.core.arbiter.holds)
        self._attr_extra_state_attributes = {"holds": dict(self.core.arbiter.holds),
                                             "commands": dict(self.core.arbiter.commands)}
        self.async_write_ha_state()


class AsleepBelief(_Base, RestoreEntity):
    """The asleep filter, one step a minute (asleep.py has the model)"""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, core: Core) -> None:
        super().__init__(core, "asleep_belief", "Asleep belief", "mdi:sleep")
        self.model: dict = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._attr_native_value = float(last.state)
            except ValueError:
                pass
            self.model = dict(last.attributes.get("model") or {})
            self._attr_extra_state_attributes = {"model": self.model}
        self.async_on_remove(async_track_time_change(self.hass, self._step, second=0))

    @callback
    def _step(self, _now: datetime | None = None) -> None:
        core, view = self.core, self.core.view
        now = dt_util.now()
        prev = (self._attr_native_value if self._attr_native_value is not None else 5) / 100
        life = when(view.state("sensor.last_sign_of_life"))
        quiet = (now - life).total_seconds() / 60 if life is not None else 999
        last_at = float(self.model.get("at", now.timestamp() - 60))
        seen = Seen(
            hour=now.hour, quiet_minutes=quiet,
            active=life is not None and life.timestamp() >= last_at,
            typing=view.is_on("binary_sensor.at_the_desk"),
            home=(view.state("person.resident") == "home" or view.is_on("binary_sensor.phone_on_home_wifi")
                  or view.state("input_select.house_mode") != "Away"),
            night=view.state("input_select.house_mode") == "Night",
            lights_on=any(view.is_on(e) for lab in LAYER_LABELS[:2] for e in view.tagged(lab)),
            on_charger=view.is_on("input_boolean.phone_on_charger"),
            focus=view.is_on("binary_sensor.phone_focus"),
            tv_picture=view.is_on("binary_sensor.tv_picture"),
            bedroom_door_shut=view.state("binary_sensor.bedroom_door") == "off",
            waking_up=view.is_on("input_boolean.waking_up"),
        )
        self.model = {**asleep_next(prev, seen, core.p), "at": round(now.timestamp(), 1)}
        self._attr_native_value = round(self.model["b"] * 100, 1)
        self._attr_extra_state_attributes = {"model": self.model}
        self.async_write_ha_state()
        for fn in core.belief_listeners:
            fn(self._attr_native_value)


class LightCurve(_Base):
    """The light curve, worked out every minute and whenever tonight's plan changes. The looks work
    it out fresh for themselves; this is for reading (the dashboard, and when Calm starts)"""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, core: Core) -> None:
        super().__init__(core, "light_curve", "Light curve", "mdi:theme-light-dark")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_change(self.hass, self._update, second=0))
        self.async_on_remove(async_track_state_change_event(
            self.hass, ["sensor.bedtime_plan", "input_number.wind_down_hours"], self._update))
        self._update()

    @callback
    def _update(self, _event: Event | datetime | None = None) -> None:
        c = self.core.curve()
        self._attr_native_value = c.pop("level")
        self._attr_extra_state_attributes = c
        self.async_write_ha_state()
