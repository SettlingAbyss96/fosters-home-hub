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


# the digest on the Hub and the AI task, for the morning (packages/morning.yaml, digest.yaml)
MORNING_KIT = {"status": 200, "content": {
    "kit": "m1", "format": "one story", "length": "four or five short spoken sentences, about twenty-five seconds",
    "items": 1, "shelves": ["market"],
    "brief": ("How to tell it this time: one story.\n\n"
              "[1] Almost Daily Grant's (October 12): \"All Together Now\". The S&P 500 looks like two markets.")}}
MORNING_WORDS = {"data": ("Good morning. Clear and seventy, and nothing on the calendar. The doorbell rang once "
                          "at 2:14, and the car finished charging. Grant's reckons the S&P is really two markets now.")}
DIGEST = {"input_text.hub_address": "192.0.2.10", "ai_task.jarvis_writer": "unknown"}
CAR = {"title": "Car", "message": "The car's done charging at 80% and still plugged in.", "data": {"tag": "car_unplug"}}


async def a_night(house, unplugged=False):
    """From 1:50: the doorbell at 2:14, the car's reminder three times from 3:00, and maybe unplugged"""
    await house.advance(minutes=24)
    await house.hass.services.async_call("input_datetime", "set_datetime", {
        "entity_id": "input_datetime.doorbell_last_ring", "datetime": f"{TUESDAY} 02:14:00"}, blocking=True)
    await house.advance(minutes=46)
    for _ in range(3):
        await house.hass.services.async_call("notify", "mobile_app_phone", CAR, blocking=True)
        await house.advance(minutes=10)
    if unplugged:
        await house.hass.services.async_call("notify", "mobile_app_phone",
                                             {"message": "clear_notification", "data": {"tag": "car_unplug"}}, blocking=True)


async def up(house):
    house.set("binary_sensor.hub_500_motion", "on")
    await house.advance(seconds=30)
    house.set("binary_sensor.hub_500_motion", "off")
    await house.settle()


async def test_the_morning_has_the_night_in_it_and_something_new(house_at):
    # a briefing whose overnight is only a printer finishing says nothing about a night like this
    house = await house_at(f"{TUESDAY} 01:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    await a_night(house)
    await house.advance(minutes=117)                  # 5:27, up
    await up(house)
    asks = house.called("ai_task.generate_data", entity_id="ai_task.jarvis_writer")
    assert asks, "written from the digest's kit"
    text = asks[-1].data["instructions"]
    assert "The doorbell rang at 2:14" in text
    assert "Car: The car's done charging at 80% and still plugged in at 3:00, 3 times, the last at 3:20" in text
    assert "clear_notification" not in text and "Wake up:" not in text
    assert "All Together Now" in text
    assert not house.called("conversation.process"), "the kit's the news, no web search"
    assert house.said("Grant's reckons the S&P is really two markets")
    told = house.called("rest_command.digest_told")
    assert len(told) == 1 and told[0].data["kit"] == "m1", "heard, so retired"


async def test_up_at_four_for_a_few_minutes_isnt_the_morning(house_at):
    # the Hub seeing someone at 4:00, an hour and a half before the alarm, used to be the briefing in
    # an empty room at 4:01 and nothing when they were really up at 5:55
    house = await house_at(f"{TUESDAY} 03:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    await house.advance(minutes=10)                   # 4:00
    await up(house)
    await house.advance(minutes=2)
    assert not house.said("Grant's reckons"), "a night trip, not the morning"
    await house.advance(minutes=113)                  # 5:55, the wake-up's been
    await up(house)
    await house.advance(seconds=30)
    assert house.said("Grant's reckons the S&P is really two markets")


async def test_words_older_than_the_night_are_written_again(house_at):
    # words written at the sunrise, then a notification before you're up: they're written again
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    await house.advance(minutes=6)                    # 4:56, written at the sunrise
    first = len(house.called("ai_task.generate_data"))
    assert first == 1
    await house.hass.services.async_call("notify", "mobile_app_phone", CAR, blocking=True)
    await house.advance(minutes=30)                   # 5:26, up after something came through
    await up(house)
    assert len(house.called("ai_task.generate_data")) == first + 1, "written again, with the car in it"
    assert "Car: The car's done" in house.called("ai_task.generate_data")[-1].data["instructions"]


async def test_asking_again_is_todays_briefing_in_full(house_at):
    # asked again after it's been said, it's the whole briefing, not the house's short version
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    await house.advance(minutes=37)
    await up(house)
    assert house.said("Grant's reckons")
    assert await house.ask("MorningBriefing") == MORNING_WORDS["data"]
    assert len(house.called("rest_command.digest_told")) == 1, "retired once, not again for a repeat"


async def test_asked_for_before_the_hub_sees_me_its_written_then(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    house.set("input_boolean.auto_briefing", "on")
    await house.advance(minutes=2)                    # 4:52, before the sunrise writes anything
    assert await house.ask("MorningBriefing") == MORNING_WORDS["data"]
    assert house.state("input_select.house_mode") == "Morning"
    house.forget()
    await house.advance(minutes=40)
    await up(house)
    assert not house.said("Grant's reckons"), "said is said: not again when the Hub sees me"


async def test_a_reminder_already_dealt_with_isnt_said_again(house_at):
    # the car got unplugged, which cleared its notification: the morning doesn't remind you twice
    house = await house_at(f"{TUESDAY} 01:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    await a_night(house, unplugged=True)
    await house.advance(minutes=117)
    await up(house)
    text = house.called("ai_task.generate_data")[-1].data["instructions"]
    assert "The doorbell rang at 2:14" in text
    assert "Car:" not in text


def logged(house):
    """What's in the house log, without its Night markers"""
    return [e["what"] for e in house.attr("sensor.house_log", "entries") or [] if e["key"] != "night"]


async def test_a_restart_is_only_news_when_something_didnt_come_back(house_at):
    # a day of deploys restarts Home Assistant over and over, and everything comes back. A log that
    # kept every one would read them out in the morning
    house = await house_at(f"{TUESDAY} 01:50", {"input_select.house_mode": "Night", **DIGEST})
    house.replies["rest_command.digest_kit"] = MORNING_KIT
    house.replies["ai_task.generate_data"] = MORNING_WORDS
    restarted = {"entity_id": "automation.something_didn_t_come_back_after_a_restart"}
    await house.hass.services.async_call("automation", "trigger", restarted)
    await house.advance(minutes=15)
    assert not logged(house), "all back: nothing to say"
    house.set("vacuum.robot_vacuum", "unavailable", friendly_name="Robot vacuum")
    await house.hass.services.async_call("automation", "trigger", restarted)
    await house.advance(minutes=200)                  # 5:25, up
    await up(house)
    text = house.called("ai_task.generate_data")[-1].data["instructions"]
    assert "Still offline ten minutes after Home Assistant restarted: Robot vacuum" in text
    assert text.count("restarted") == 1


async def test_the_backup_is_only_news_when_it_failed(house_at):
    house = await house_at(f"{TUESDAY} 01:50", {"input_select.house_mode": "Night",
                                                "sensor.backup_last_attempted_automatic_backup": "2026-10-12T05:17:04+00:00",
                                                "sensor.backup_last_successful_automatic_backup": "2026-10-12T05:17:17+00:00"})
    house.set("sensor.backup_last_attempted_automatic_backup", "2026-10-13T05:50:04+00:00")
    await house.advance(seconds=15)
    house.set("sensor.backup_last_successful_automatic_backup", "2026-10-13T05:50:19+00:00")
    await house.advance(minutes=45)
    assert not logged(house), "a backup that worked is no news"
    house.set("sensor.backup_last_attempted_automatic_backup", "2026-10-13T06:40:04+00:00")
    await house.advance(minutes=45)
    assert logged(house) == ["Home Assistant's backup failed"]


def sleep_night(score, hours, month=72, month_h=6.9, week=None):
    return {"sensor.oura_ring_bedtime_end": f"{TUESDAY}T09:10:00+00:00",
            "sensor.oura_ring_sleep_score": (str(score), {"data_date": TUESDAY}),
            "sensor.oura_ring_total_sleep_duration": str(hours),
            "sensor.oura_ring_readiness_score": ("58", {"data_date": TUESDAY}),
            "sensor.health_trends": ("x", {"sleep_score_30d": month, "sleep_hours_30d": month_h,
                                           "sleep_score_7d": week if week is not None else month})}


async def test_a_bad_night_is_said_plainly_against_my_month(house_at):
    house = await house_at(f"{TUESDAY} 05:30", {"input_select.house_mode": "Morning", **sleep_night(55, 5.2, week=64)})
    out = await house.hass.services.async_call("script", "morning_briefing_text", {}, blocking=True, return_response=True)
    assert "You slept 5 hours 12, sleep score 55, readiness 58." in out["text"]
    assert "17 points under your 30-day average of 72, and 102 minutes less sleep than usual" in out["text"]
    assert "This week's average is 64, against 72 for the month." in out["text"]


async def test_an_ordinary_night_is_just_its_numbers(house_at):
    house = await house_at(f"{TUESDAY} 05:30", {"input_select.house_mode": "Morning", **sleep_night(70, 6.8)})
    out = await house.hass.services.async_call("script", "morning_briefing_text", {}, blocking=True, return_response=True)
    assert "sleep score 70" in out["text"]
    assert "30-day average" not in out["text"] and "This week" not in out["text"], "inside the deadband"
