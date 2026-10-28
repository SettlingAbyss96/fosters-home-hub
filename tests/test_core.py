"""The control core (custom_components/house_control) taking over from the templates it replaced:
a house that ran the old arbiter and asleep filter keeps the same entities, their history and what
they were holding when it restarted, and the automation that used to spot a hand at the switch
goes."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import mock_restore_cache

from house import TZ

TUESDAY = "2026-10-13"


async def test_a_house_on_the_old_templates_moves_over_with_its_holds(hass, house_at):
    reg = er.async_get(hass)
    for domain, uid in [("sensor", "light_arbiter"), ("sensor", "asleep_belief"), ("binary_sensor", "asleep")]:
        reg.async_get_or_create(domain, "template", uid, suggested_object_id=uid)
    reg.async_get_or_create("automation", "automation", "light_changed_by_hand",
                            suggested_object_id="light_changed_by_hand")
    # what the template arbiter was holding when Home Assistant stopped: the alarm's hold on the
    # bedroom light, another two hours of it (the alarm's, since nothing overrides that one)
    at = datetime.fromisoformat(f"{TUESDAY} 23:30").replace(tzinfo=ZoneInfo(TZ))
    until = (at + timedelta(hours=2)).timestamp()
    mock_restore_cache(hass, [
        State("sensor.light_arbiter", "1", {"holds": {"light.bedroom_light": {"priority": 1, "until": until, "source": "wake-up"}},
                                            "commands": {}}),
        State("sensor.asleep_belief", "92.0", {"model": {"b": 0.92, "at": at.timestamp() - 60}}),
        State("binary_sensor.asleep", "on"),
    ])
    house = await house_at(f"{TUESDAY} 23:30", {"input_select.house_mode": "Night"})

    for entity in ("sensor.light_arbiter", "sensor.asleep_belief", "binary_sensor.asleep"):
        entry = reg.async_get(entity)
        assert entry is not None and entry.platform == "house_control", f"{entity} is the core's now"
        assert reg.async_get(entity + "_2") is None, f"no {entity}_2 beside the old one"
    assert reg.async_get("automation.light_changed_by_hand") is None, "the old by-hand automation is gone"
    assert "light.bedroom_light" in (house.attr("sensor.light_arbiter", "holds") or {}), "the hold came along"
    assert house.state("binary_sensor.asleep") == "on", "and the house still thinks you're asleep"
