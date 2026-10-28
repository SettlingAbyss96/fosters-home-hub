"""binary_sensor.asleep: the asleep belief with hysteresis, on at 85% and off at 35%, so a value near
the line doesn't flick back and forth"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN, Core
from .blocks import schmitt


async def async_setup_platform(hass: HomeAssistant, config: Any, add: AddEntitiesCallback,
                               discovery_info: Any = None) -> None:
    add([Asleep(hass.data[DOMAIN])])


class Asleep(BinarySensorEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_unique_id = "asleep"
    _attr_name = "Asleep"
    _attr_icon = "mdi:sleep"

    def __init__(self, core: Core) -> None:
        self.core = core
        self.entity_id = "binary_sensor.asleep"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._attr_is_on = last is not None and last.state == "on"
        self.core.belief_listeners.append(self._belief)
        belief = self.hass.states.get("sensor.asleep_belief")
        if belief is not None:
            try:
                self._belief(float(belief.state))
                return
            except ValueError:
                pass
        self.async_write_ha_state()

    @callback
    def _belief(self, percent: float) -> None:
        p = self.core.p
        self._attr_is_on = schmitt(percent / 100, p["asleep_on"], p["asleep_off"], bool(self._attr_is_on))
        self.async_write_ha_state()
