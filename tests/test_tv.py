"""The TV's status and power as the house reads them from dumpsys (packages/tv.yaml)."""

TUESDAY = "2026-10-13"


def answers(house, response):
    """The TV answering every ADB command with this"""
    house.set("media_player.fire_tv", "off", adb_response=response)


async def test_a_tv_dozing_after_its_sleep_timer_is_off(house_at):
    # off on its own timer, a TV can sit in a screen-off doze, which read as On until this
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening"})
    answers(house, "  mWakefulness=Dozing\n  mCurrentFocus=null\n")
    house.hass.bus.async_fire("tv_changed", {})
    await house.advance(seconds=2)
    assert house.state("sensor.tv_status") == "Off"


async def test_off_when_its_already_dozing_is_done(house_at):
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening"})
    answers(house, "  mWakefulness=Dozing\n")
    response = await house.hass.services.async_call("script", "tv_power", {"power": "off"}, blocking=True, return_response=True)
    await house.settle()
    assert response["done"] is True
    assert not house.called("androidtv.adb_command", command="input keyevent KEYCODE_SLEEP"), "nothing to do"


async def test_an_asleep_tv_only_gets_asked_if_its_awake_and_keeps_its_volume(house_at):
    # the whole reading every 15 s comes to about 5,800 a day, mostly to a TV that's off. Asleep it
    # only answers the first question, and its volume and mute stay
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening"})
    home = "mWakefulness=Awake\n  mCurrentFocus=Window{1 u0 com.amazon.tv.launcher/x}\n"
    for muted, volume in (("true", None), ("false", 12)):
        answers(house, home + f"   Muted: {muted}\n   streamVolume:12\n")
        house.hass.bus.async_fire("tv_changed", {})
        await house.advance(seconds=2)
        assert house.state("sensor.tv_status") == "Home screen"
        answers(house, "mWakefulness=Asleep\n")
        house.hass.bus.async_fire("tv_changed", {})
        await house.advance(seconds=2)
        assert house.state("sensor.tv_status") == "Off"
        assert house.attr("sensor.tv_status", "muted") is (muted == "true")
        assert house.attr("sensor.tv_status", "volume") == volume
    command = house.called("androidtv.adb_command")[-1].data["command"]
    assert "*Asleep*|*Dozing*) ;;" in command, "asleep, nothing past the first question"
