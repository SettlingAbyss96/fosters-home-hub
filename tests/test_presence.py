"""Leaving and coming home, with and without the phone (packages/presence.yaml, occupancy.yaml).
The template is a day the phone spends somewhere else: home without it in the afternoon, out again
in the evening, and back with it later to a house that should put the whole look back."""

from homeassistant.components.light import ColorMode

from house import HOME_WIFI

TUESDAY = "2026-10-13"
DUSK = ("above_horizon", {"elevation": 2})
OUT = {"person.resident": "not_home", "sensor.phone_ssid": "Somewhere else"}


async def door(house, *, then=None):
    """Open and close the front door, and optionally something moving inside afterwards"""
    house.set("binary_sensor.front_door", "on")
    await house.advance(seconds=5)
    house.set("binary_sensor.front_door", "off")
    await house.advance(seconds=20)
    if then:
        house.set(then, "on")
        await house.advance(seconds=30)
        house.set(then, "off")
        await house.settle()


def manual(house):
    return [d for kind, d in house.events if kind == "light_manual"]


async def test_leaving_without_the_phone_goes_away(house_at):
    house = await house_at(f"{TUESDAY} 18:30", {"input_select.house_mode": "Evening", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    house.set("binary_sensor.hub_500_motion", "on")      # someone's in, without the phone
    await house.advance(seconds=30)
    house.set("binary_sensor.hub_500_motion", "off")
    await house.advance(minutes=12)
    assert house.state("binary_sensor.someone_home") == "on"
    await door(house)                                    # out again
    await house.advance(minutes=3)
    assert house.state("input_select.house_mode") == "Evening", "still checking: maybe someone's in"
    await house.advance(minutes=3)
    assert house.state("binary_sensor.someone_home") == "off"
    assert house.state("input_select.house_mode") == "Away"


async def test_coming_in_without_the_phone(house_at):
    house = await house_at(f"{TUESDAY} 17:30", {"input_select.house_mode": "Away", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    await door(house, then="binary_sensor.hub_500_motion")
    await house.advance(seconds=10)
    assert house.state("input_select.house_mode") == "Evening"
    assert house.is_on("light.bedroom_lamp"), "the Evening look, bedroom lamp and all"
    assert house.phoned("Someone came in")
    assert not house.said("Welcome home"), "could be a guest"


async def test_a_guest_keeps_the_house_when_i_leave(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    await door(house, then="binary_sensor.hub_500_motion")   # out the door, someone moves inside after
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=15)
    assert house.state("input_select.house_mode") == "Day"
    assert house.phoned("still home")


async def test_leaving_with_the_phone_waits_for_the_door_check(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    await door(house)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=3)
    assert house.state("input_select.house_mode") == "Day"
    await house.advance(minutes=3)
    assert house.state("input_select.house_mode") == "Away"


async def test_a_lamp_switched_off_from_the_app_on_the_way_out_isnt_someone_in(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    house.by_hand("light.bedroom_lamp", "on", 60)
    await house.advance(minutes=1)
    await door(house)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=2)
    house.by_hand("light.bedroom_lamp", "off", app=True)   # from the stairs, forgot it was on
    await house.advance(minutes=10)
    assert {"entity": "light.bedroom_lamp", "by": "app"}.items() <= manual(house)[-1].items()
    assert house.state("input_select.house_mode") == "Away"
    assert not house.phoned("still home")


async def test_a_light_switched_at_the_wall_after_i_leave_is_someone_in(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    house.by_hand("light.bedroom_lamp", "on", 60)
    await house.advance(minutes=1)
    await door(house)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=2)
    house.by_hand("light.bedroom_lamp", "off")
    await house.advance(minutes=10)
    assert {"entity": "light.bedroom_lamp", "by": "wall"}.items() <= manual(house)[-1].items()
    assert house.state("input_select.house_mode") == "Day"
    assert house.attr("binary_sensor.someone_home", "why") == "a light switched at the wall"


async def test_leaving_after_the_alarm_switches_the_bedroom_off(house_at):
    # the alarm at 5:25 holds the bedroom light and lamp on (priority 1), and leaving an hour later
    # the Away look couldn't touch them
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", "binary_sensor.front_door": "off"})
    await house.advance(minutes=40)
    assert house.level("light.bedroom_light") == 100
    house.hass.bus.async_fire("wake_up_confirmed", {})
    await house.advance(minutes=60)                       # 6:30
    await door(house)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=12)
    assert house.state("input_select.house_mode") == "Away"
    assert not house.is_on("light.bedroom_light")
    assert not house.is_on("light.bedroom_lamp")


async def test_leaving_switches_off_a_lamp_i_switched_on_by_hand(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    house.by_hand("light.living_room_lamp", "on", 70)
    await house.advance(minutes=5)
    await door(house)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=12)
    assert house.state("input_select.house_mode") == "Away"
    assert not house.is_on("light.living_room_lamp"), "the hold was for me being here"


async def test_no_door_sensor_leaves_like_before(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day"})
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=4)
    assert house.state("input_select.house_mode") == "Away"


async def test_coming_home_puts_the_whole_look_back(house_at):
    # already in Evening (set by hand while the phone was away), the lamp switched off by hand before
    # going out, then home with the phone
    house = await house_at(f"{TUESDAY} 20:15", {"input_select.house_mode": "Evening", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    house.by_hand("light.bedroom_lamp", "off")
    house.by_hand("light.living_room_lamp", "off")
    await house.advance(minutes=1)
    house.set("person.resident", "home")
    await house.advance(minutes=2)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=30)
    house.set("binary_sensor.front_door", "on")
    await house.advance(seconds=10)
    assert house.is_on("light.bedroom_lamp")
    assert house.is_on("light.living_room_lamp"), "a hold from before going out doesn't count"


async def test_the_doorbell_is_quiet_about_me_coming_in(house_at):
    house = await house_at(f"{TUESDAY} 20:15", {"input_select.house_mode": "Away", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", "binary_sensor.face_unknown": "off", **OUT})
    house.set("person.resident", "home")
    await house.advance(minutes=2)
    house.set("binary_sensor.face_unknown", "on")        # the doorbell didn't know my face
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=10)
    house.set("binary_sensor.front_door", "on")
    await house.advance(seconds=40)
    assert not house.called("script.tell_resident") or not any(
        "front door for a bit" in str(c.data) for c in house.calls), "no lingering alert on my own arrival"
    assert not any("front door for a bit" in str(c.data) for c in house.called("notify.mobile_app_phone"))


async def test_the_lights_go_off_the_minute_the_phone_has_gone_too(house_at):
    # the door shuts, the phone's Wi-Fi says the car a few minutes later: Away is the later of the
    # two, the house empty by the door (5 minutes) and the phone gone, not five more on top
    house = await house_at(f"{TUESDAY} 19:50", {"input_select.house_mode": "Evening", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off"})
    await house.run("lights_look", look="evening")
    assert house.is_on("light.living_room_lamp")
    await door(house)
    await house.advance(minutes=4)
    assert house.state("input_select.house_mode") == "Evening", "the phone's still on the Wi-Fi"
    await house.advance(minutes=1, seconds=30)
    house.set("sensor.phone_ssid", "Car hotspot")
    house.set("person.resident", "not_home")
    await house.advance(seconds=10)
    assert house.state("input_select.house_mode") == "Away"
    assert not house.is_on("light.living_room_lamp")
    assert not house.is_on("light.bedroom_lamp")


async def test_the_car_starting_is_leaving(house_at):
    house = await house_at(f"{TUESDAY} 19:50", {"input_select.house_mode": "Evening", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off"})
    await house.run("lights_look", look="evening")
    await door(house)
    await house.advance(minutes=1)
    house.hass.bus.async_fire("phone_signal", {"what": "car_started"})   # still in the zone, still on the Wi-Fi
    await house.advance(seconds=5)
    assert house.state("input_select.house_mode") == "Away"
    assert not house.is_on("light.living_room_lamp")


async def test_the_car_starting_with_someone_moving_inside_isnt_leaving(house_at):
    house = await house_at(f"{TUESDAY} 19:50", {"input_select.house_mode": "Evening", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off"})
    await door(house, then="binary_sensor.hub_500_motion")
    house.hass.bus.async_fire("phone_signal", {"what": "car_started"})
    await house.advance(seconds=5)
    assert house.state("input_select.house_mode") == "Evening"


async def test_the_door_opening_after_the_doorbell_sees_me_is_the_moment(house_at):
    # the doorbell sees you two seconds before the door opens: the lights go with the door, not
    # after the doorbell's seven seconds
    house = await house_at(f"{TUESDAY} 21:30", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off",
                                                "binary_sensor.doorbell_motion": "off", **OUT})
    house.set("person.resident", "home")
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=10)
    house.set("binary_sensor.doorbell_motion", "on")
    await house.advance(seconds=2, step=1)
    house.set("binary_sensor.front_door", "on")
    await house.advance(seconds=2, step=1)
    assert house.state("input_select.house_mode") != "Away"
    assert house.is_on("light.bedroom_lamp"), "on with the door, not five seconds later"


WORDS = {"response": {"speech": {"plain": {"speech": (
    "Welcome home. The Bambu finished its print. Stocks closed a touch higher today, "
    "and the weekend looks dry.")}}}}


async def arrive(house):
    """The usual way in: the zone's edge, the Wi-Fi, the door, the Hub"""
    house.set("person.resident", "home")
    await house.advance(minutes=6)
    house.set("sensor.phone_ssid", HOME_WIFI)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=10)
    await door(house, then="binary_sensor.hub_500_motion")


async def test_the_welcome_is_written_on_the_way_and_is_only_good_news(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Away", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    house.replies["conversation.process"] = WORDS
    await arrive(house)
    asks = house.called("conversation.process", agent_id="conversation.jarvis_cloud")
    assert len(asks) == 1, "written once, on the way in"
    assert "top story" in asks[0].data["text"] and "Nothing alarming" in asks[0].data["text"]
    assert house.said("the weekend looks dry")
    assert not house.said("lubrication") and not house.said("Paused")


async def test_back_again_the_same_evening_is_just_welcome_back(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Away", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    house.replies["conversation.process"] = WORDS
    await arrive(house)
    await door(house)                                     # out again at about 7:45
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Car hotspot")
    await house.advance(minutes=7)
    assert house.state("input_select.house_mode") == "Away"
    await house.advance(minutes=90)
    house.forget()
    await arrive(house)
    assert house.said("Welcome back.")
    assert not house.called("conversation.process"), "no second round of news"


async def test_no_words_from_the_agent_is_still_a_welcome(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Away", "sun.sun": DUSK,
                                                "binary_sensor.front_door": "off", **OUT})
    await arrive(house)                                   # the agent answers nothing
    await house.advance(seconds=30)
    assert house.said("Welcome home.")


async def test_home_before_the_clock_says_evening_the_floor_lamp_is_warm(house_at):
    # the morning look leaves the floor lamp at 4000 K, and a welcome that switches it on with only a
    # brightness brings it back at that: home before the clock says Evening means a cold white lamp
    house = await house_at(f"{TUESDAY} 17:40", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off",
                                                "sun.sun": ("above_horizon", {"elevation": 12}), **OUT})
    lamp = house.lights["light.living_room_lamp"]
    lamp._attr_color_mode, lamp._attr_color_temp_kelvin = ColorMode.COLOR_TEMP, 4000
    await arrive(house)
    assert house.state("input_select.house_mode") == "Day"
    assert house.is_on("light.living_room_lamp")
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") <= 2700


async def test_the_room_is_lit_before_the_door_opens(house_at):
    # a doorbell sees you 2 to 6 seconds before you're through the door, and the phone's already on
    # the Wi-Fi: the welcome goes then, and the door finds the room lit
    house = await house_at(f"{TUESDAY} 20:10", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off",
                                                "binary_sensor.doorbell_motion": "off", **OUT})
    house.set("person.resident", "home")
    house.set("sensor.phone_ssid", HOME_WIFI)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=10)
    house.set("binary_sensor.doorbell_motion", "on")
    await house.advance(seconds=3, step=1)
    assert house.is_on("light.living_room_lamp"), "lit at the doorbell"
    house.set("binary_sensor.front_door", "on")
    await house.advance(seconds=5, step=1)
    house.set("binary_sensor.front_door", "off")
    await house.advance(seconds=20)
    assert float(house.state("sensor.door_to_light")) < 0, "lit before the door opened"


async def test_the_welcome_in_calm_is_a_warm_white(house_at):
    # Calm is on the curve like the rest of the day, a warm white at 2700 K, not a colour
    house = await house_at(f"{TUESDAY} 21:45", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off", **OUT})
    await arrive(house)
    assert house.state("input_select.house_mode") == "Calm"
    assert house.attr("light.living_room_lamp", "color_mode") == "color_temp"
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 2700


async def test_picking_away_by_hand_is_leaving(house_at):
    # Away from the app on the way to the car: the wake-up's hold kept the bedroom lamp on, and with the
    # house already Away when the phone left, nothing asked about the vacuum. Now it's the whole routine
    from homeassistant.core import Context
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", "binary_sensor.front_door": "off",
                                                "sensor.robot_vacuum_battery": "100"})
    await house.advance(minutes=40)
    assert house.is_on("light.bedroom_lamp")
    house.hass.bus.async_fire("wake_up_confirmed", {})
    await house.advance(minutes=60)                       # 6:30, the hold runs to 6:40
    await door(house)
    me = await house.hass.auth.async_create_user("Resident", group_ids=["system-admin"])
    await house.hass.services.async_call("input_select", "select_option",
                                         {"entity_id": "input_select.house_mode", "option": "Away"},
                                         blocking=True, context=Context(user_id=me.id))
    await house.advance(seconds=20)
    assert not house.is_on("light.bedroom_lamp")
    assert not house.is_on("light.bedroom_light")
    assert len(house.phoned("Vacuum while you're out?")) == 1
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=6)
    assert len(house.phoned("Left home")) == 1, "the phone going later doesn't run it twice"


async def test_away_by_hand_then_out_of_the_door_stays_away(house_at):
    # Away picked inside, then out: the door on the way out isn't a way in
    house = await house_at(f"{TUESDAY} 07:00", {"input_select.house_mode": "Day", "binary_sensor.front_door": "off"})
    await house.run("house_mode_set", mode="Away")
    await house.advance(seconds=20)
    await door(house)
    await house.advance(minutes=1)
    assert house.state("input_select.house_mode") == "Away"


async def test_home_by_the_gps_alone_isnt_home(house_at):
    # the GPS saying home from just outside, with no Wi-Fi and no door: the old fallback lit the empty
    # flat after 15 minutes. Nothing now until the door
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off", **OUT})
    house.set("person.resident", "home")
    await house.advance(minutes=20)
    assert house.state("input_select.house_mode") == "Away"
    assert not house.is_on("light.living_room_lamp")
    await house.advance(minutes=47)
    house.set("sensor.phone_ssid", HOME_WIFI)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=5)
    await door(house)
    assert house.state("input_select.house_mode") != "Away"
    assert house.is_on("light.living_room_lamp")


async def test_a_door_that_opens_after_the_wait_still_counts(house_at):
    # on the Wi-Fi but outside for a while: nothing until the door, then the door is the moment
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Away", "binary_sensor.front_door": "off", **OUT})
    house.set("person.resident", "home")
    house.set("sensor.phone_ssid", HOME_WIFI)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(minutes=16)
    assert house.state("input_select.house_mode") == "Away", "a working door that never opened"
    await door(house)
    assert house.state("input_select.house_mode") != "Away"
    assert house.is_on("light.bedroom_lamp")


async def test_a_dead_door_sensor_falls_back_to_the_wifi(house_at):
    # a door sensor that isn't answering: the phone on the Wi-Fi for a minute is the sign then
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Away", "binary_sensor.front_door": "unavailable", **OUT})
    house.set("person.resident", "home")
    await house.advance(minutes=2)
    house.set("sensor.phone_ssid", HOME_WIFI)
    house.hass.bus.async_fire("home_wifi_joined", {})
    await house.advance(seconds=30)
    assert house.state("input_select.house_mode") == "Away"
    await house.advance(seconds=60)
    assert house.state("input_select.house_mode") != "Away"
    assert house.is_on("light.living_room_lamp")


async def test_the_vacuum_started_on_the_way_out_gets_to_clean(house_at):
    # paused, and started from the vacuum's own app on the way out of the door: that's you. Any
    # other time it's the app's schedule, and paused means paused
    house = await house_at(f"{TUESDAY} 18:30", {"input_select.house_mode": "Evening", "binary_sensor.front_door": "off",
                                                "input_boolean.auto_vacuum": "off"})
    await door(house)
    house.set("vacuum.robot_vacuum", "cleaning")
    await house.advance(seconds=10)
    assert not house.called("vacuum.return_to_base")
    house.set("vacuum.robot_vacuum", "docked")
    await house.advance(minutes=10)
    house.set("vacuum.robot_vacuum", "cleaning")
    await house.advance(seconds=10)
    assert house.called("vacuum.return_to_base")
