"""The morning. Every one of these runs the real automations on a frozen Tuesday, through the
same trigger path a real morning takes: an alarm tested by calling its script directly can pass
every test and still never start on its own."""

import pytest
from homeassistant.core import Context

TUESDAY = "2026-10-13"  # a workday: the bench's plan works back from 7:00 to a 5:25 wake (tests/house.py)


async def test_the_alarm_runs_by_itself(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.advance(minutes=6)
    assert house.state("script.wake_up") == "on", "the wake-up should start 30 minutes out"
    assert house.is_on("light.bedroom_light")

    await house.advance(minutes=30)  # 5:26
    assert house.said("Good morning")
    assert house.level("light.bedroom_light") == 100
    assert house.state("input_select.house_mode") == "Morning"

    await house.advance(minutes=10)  # 5:36, nobody seen
    assert house.said("Time to get up")
    assert house.phoned("Time to get up")


@pytest.mark.expect_errors("didn't answer")
async def test_a_dead_bedroom_light_doesnt_stop_the_alarm(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    house.dead.add("light.bedroom_light")
    await house.advance(minutes=36)
    assert house.said("Good morning")
    assert house.is_on("light.bedroom_lamp"), "the lamp still comes on"
    await house.advance(minutes=10)
    assert house.said("Time to get up")


async def test_the_alarm_starts_with_the_plan_broken(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    house.hass.states.async_set("sensor.bedtime_plan", "unavailable", {})
    await house.advance(minutes=36)
    assert house.said("Good morning"), "a workday has a wake time even without the plan"


async def test_the_backstop_when_the_wake_up_never_starts(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.wake_up_starts_before_the_wake_time"}, blocking=True)
    await house.advance(minutes=40)  # 5:30
    assert house.phoned("backup alarm"), "the backstop should go off 3 minutes past the wake time"
    assert house.said("Time to get up")


async def test_seen_up_before_the_wake_time_means_no_alarm(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.advance(minutes=20)  # 5:10, up early
    house.set("binary_sensor.hub_500_motion", "on")
    await house.settle()
    house.set("binary_sensor.hub_500_motion", "off")
    await house.advance(minutes=30)  # 5:40
    # (the morning briefing says good morning when the Hub sees someone, that's right; the alarm's
    # own good morning is the one with the time in it)
    assert not house.said("Good morning. It's 5:2")
    assert not house.said("Time to get up")
    assert not house.phoned("backup alarm")


async def test_typing_at_the_computer_stops_the_alarm(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.advance(minutes=37)  # 5:27, past good morning
    assert house.said("Good morning")
    house.forget()
    house.set("sensor.computer_session_state", "Unlocked")
    house.set("sensor.computer_last_active", house.now().isoformat())
    await house.settle()
    assert house.attr("sensor.seen_up", "how") == "typing at the computer"
    await house.advance(minutes=15)
    assert not house.said("Time to get up")


async def test_saying_im_up_stops_the_alarm(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.advance(minutes=37)
    house.forget()
    house.hass.bus.async_fire("wake_up_confirmed", {}, context=Context())
    await house.settle()
    await house.advance(minutes=15)
    assert not house.said("Time to get up")
    assert house.state("input_datetime.wake_up_seen").startswith(TUESDAY)


BRIEFING = {"response": {"speech": {"plain": {"speech": (
    "Good morning. Sunny and eighty-four today, first meeting at seven. Futures are pointing up, "
    "and the weekend looks dry.")}}}}


async def test_the_morning_briefing_is_written_at_sunrise_and_is_good_news(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    house.replies["conversation.process"] = BRIEFING
    await house.advance(minutes=6)                    # 4:56, the sunrise has started
    asks = house.called("conversation.process", agent_id="conversation.jarvis_cloud")
    assert len(asks) == 1, "written ahead, once"
    assert "top story" in asks[0].data["text"] and "needs" not in asks[0].data["text"]
    await house.advance(minutes=31)                   # 5:27, up
    house.set("binary_sensor.hub_500_motion", "on")
    await house.advance(seconds=30)
    house.set("binary_sensor.hub_500_motion", "off")
    await house.settle()
    assert house.said("Futures are pointing up")
    assert house.is_on("light.bedroom_lamp"), "the bedside lamp's on when someone's up"
    assert not house.is_on("light.kitchen_light")


async def test_without_the_words_the_briefing_is_short_and_has_no_chores(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night"})
    await house.advance(minutes=37)                   # the agent never answers
    house.set("binary_sensor.hub_500_motion", "on")
    await house.advance(seconds=40)
    house.set("binary_sensor.hub_500_motion", "off")
    await house.settle()
    spoken = [str(c.data.get("message", "")) for c in house.called("assist_satellite.announce")]
    briefing = [m for m in spoken if m.startswith("Good morning.") and "It's 5:2" not in m]
    assert briefing, spoken
    assert not any(w in briefing[-1] for w in ("Paused", "lubrication", "update", "dozed"))
