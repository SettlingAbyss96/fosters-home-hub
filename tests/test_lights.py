"""Who gets the light (packages/arbiter.yaml): by hand beats the clock, asking beats by hand, the
alarm beats everything, and a light reporting back isn't a hand at the switch."""

TUESDAY = "2026-10-13"


def manual(house, entity):
    return [d for kind, d in house.events if kind == "light_manual" and d.get("entity") == entity]


async def sunset(house):
    house.set("sun.sun", "above_horizon", elevation=2)
    await house.settle()
    await house.advance(seconds=30)


async def test_a_light_set_by_hand_survives_the_clock(house_at):
    house = await house_at(f"{TUESDAY} 17:00", {"input_select.house_mode": "Day", "sun.sun": ("above_horizon", {"elevation": 10})})
    house.by_hand("light.living_room_lamp", "on", 100)
    await house.settle()
    assert manual(house, "light.living_room_lamp")[0]["by"] == "wall"

    await sunset(house)
    assert house.state("input_select.house_mode") == "Evening"
    assert house.level("light.living_room_lamp") == 100, "held: the clock's Evening wants 80"
    assert house.is_on("light.living_room_ambient"), "everything else follows the look"


async def test_a_hold_runs_out(house_at):
    house = await house_at(f"{TUESDAY} 17:00", {"input_select.house_mode": "Day", "sun.sun": ("above_horizon", {"elevation": 10})})
    house.by_hand("light.living_room_lamp", "on", 100)
    await house.settle()
    await house.advance(minutes=181)                       # 8:01 PM, into the wind-down
    await house.run("lights_look", look="evening")
    await house.advance(seconds=5)
    assert house.level("light.living_room_lamp") < 100, "the hold's gone, the look moved it"
    assert "light.living_room_lamp" not in (house.attr("sensor.light_arbiter", "holds") or {})


async def test_asking_for_a_mode_beats_a_light_set_by_hand(house_at):
    house = await house_at(f"{TUESDAY} 17:00", {"input_select.house_mode": "Day"})
    house.by_hand("light.living_room_lamp", "on", 100)
    await house.settle()
    await house.run("house_mode_set", mode="Evening")
    await house.advance(seconds=10)
    assert house.level("light.living_room_lamp") == 80
    holds = house.attr("sensor.light_arbiter", "holds") or {}
    assert "light.living_room_lamp" not in holds, "asking for a mode ends the by-hand hold"


async def test_a_light_reporting_back_isnt_a_hand(house_at):
    house = await house_at(f"{TUESDAY} 18:00", {"input_select.house_mode": "Day"})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=8)
    house.report("light.living_room_lamp", "on", 80)    # a late Matter update
    await house.advance(seconds=60)
    house.report("light.living_room_ambient", "on")      # a Kasa poll a minute later
    await house.settle()
    assert not manual(house, "light.living_room_lamp")
    assert not manual(house, "light.living_room_ambient")

    await house.advance(minutes=5)
    house.by_hand("light.living_room_lamp", "off")
    await house.settle()
    assert manual(house, "light.living_room_lamp"), "switching it off is a person"


async def test_the_dashboard_counts_as_by_hand(house_at):
    house = await house_at(f"{TUESDAY} 18:00", {"input_select.house_mode": "Day"})
    house.by_hand("light.kitchen_light", "on", 100, app=True)
    await house.settle()
    assert manual(house, "light.kitchen_light")[0]["by"] == "app"


async def test_the_alarm_beats_a_light_set_by_hand(house_at):
    house = await house_at(f"{TUESDAY} 05:00", {"input_select.house_mode": "Night"})
    house.by_hand("light.bedroom_light", "off")
    house.by_hand("light.bedroom_light", "on", 20)
    await house.settle()
    await house.run("wake_up_bedroom_full")
    assert house.level("light.bedroom_light") == 100
    # and the Morning look can't take it back down
    await house.run("lights_look", look="morning")
    assert house.level("light.bedroom_light") == 100


async def test_the_fell_asleep_check_beats_a_lamp_left_on(house_at):
    house = await house_at(f"{TUESDAY} 23:00", {"input_select.house_mode": "Night"})
    house.by_hand("light.bedroom_lamp", "on")
    await house.settle()
    await house.run("light_set", entity="light.bedroom_lamp", level=0, priority=2, source="asleep")
    assert not house.is_on("light.bedroom_lamp")


async def test_colour_and_brightness_never_fade_in_one_command(house_at):
    # the Govee lamp's firmware gets stuck mid-fade when both change in one faded command, and then
    # reports its level wobbling one step either side, forever
    house = await house_at(f"{TUESDAY} 18:00", {"input_select.house_mode": "Day"})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    lamp = [kw for e, on, kw in house.light_calls if e == "light.living_room_lamp" and on == "on"]
    assert lamp, "the evening look sets the lamp"
    for kw in lamp:
        colour = "color_temp_kelvin" in kw or "hs_color" in kw
        brightness = "brightness" in kw
        assert not (colour and brightness and kw.get("transition", 0) > 0), kw


async def test_the_morning_leaves_the_kitchen_alone(house_at):
    # a kitchen ceiling is bright enough to hurt first thing: it's on when someone asks for it
    house = await house_at(f"{TUESDAY} 05:25", {"input_select.house_mode": "Night"})
    await house.run("lights_look", look="morning")
    await house.advance(seconds=10)
    assert not house.is_on("light.kitchen_light")
    for light in ("light.bedroom_lamp", "light.living_room_ambient", "light.living_room_lamp"):
        assert house.is_on(light), light


async def test_day_keeps_the_lamps_and_the_ambient_lights_on(house_at):
    # a Day look that switches the lamps off just gets them switched back on by hand
    house = await house_at(f"{TUESDAY} 07:55", {"input_select.house_mode": "Morning"})
    await house.run("lights_look", look="morning")
    await house.advance(seconds=10)
    await house.run("lights_look", look="day")
    await house.advance(seconds=10)
    for light in ("light.bedroom_lamp", "light.living_room_ambient", "light.living_room_lamp"):
        assert house.is_on(light), light
    assert not house.is_on("light.bedroom_light"), "the sunrise light's done its job"
    assert not house.is_on("light.kitchen_light")
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 4000


PLAN = ("2026-10-14T01:40:00+00:00", {"wake": "2026-10-14T09:25:00+00:00"})   # bed 9:40 PM, up 5:25 AM


async def test_the_floor_lamp_warms_through_the_afternoon(house_at):
    house = await house_at(f"{TUESDAY} 12:30", {"input_select.house_mode": "Day", "sensor.bedtime_plan": PLAN})
    await house.run("lights_look", look="day")
    await house.advance(seconds=10)
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 4000
    await house.advance(minutes=155)                      # 3:05 PM, the blend ticks have moved it
    assert abs(house.attr("light.living_room_lamp", "color_temp_kelvin") - 2700) <= 30


async def test_the_curve_dims_with_daylight_and_into_the_wind_down(house_at):
    # full sun at 1 PM: the windows do the work, the lamp sits low. Dark at 5:30 PM: 80%. Three
    # hours before a 9:40 bedtime: 35%, and still 2700 K (the floor)
    sunny = {"input_select.house_mode": "Day", "sensor.bedtime_plan": PLAN,
             "sun.sun": ("above_horizon", {"elevation": 50}), "weather.forecast_home": ("sunny", {"cloud_coverage": 0})}
    house = await house_at(f"{TUESDAY} 13:00", sunny)
    await house.run("lights_look", look="day")
    await house.advance(seconds=10)
    assert house.level("light.living_room_lamp") == 50

    house = await house_at(f"{TUESDAY} 17:30", {"input_select.house_mode": "Evening", "sensor.bedtime_plan": PLAN})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    assert house.level("light.living_room_lamp") == 80
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 2700
    await house.advance(minutes=75)                       # 6:45 PM, the ticks have brought it down
    assert abs(house.level("light.living_room_lamp") - 35) <= 2
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 2700
    assert house.is_on("light.bedroom_lamp") and house.is_on("light.living_room_ambient"), "the plugs stay on"


async def test_a_look_never_switches_a_task_light_on(house_at):
    house = await house_at(f"{TUESDAY} 19:00", {"input_select.house_mode": "Evening"})
    for look in ("morning", "day", "evening", "calm", "welcome"):
        await house.run("lights_look", look=look)
        await house.advance(seconds=10)
        for light in ("light.kitchen_light", "light.bathroom_light", "light.bedroom_light"):
            assert not house.is_on(light), f"{look}: {light}"
    await house.run("lights_look", look="bright")         # asking for everything
    await house.advance(seconds=10)
    assert house.is_on("light.kitchen_light")


async def test_a_film_puts_the_lamps_and_the_ambient_lights_out(house_at):
    house = await house_at(f"{TUESDAY} 20:30", {"input_select.house_mode": "Evening"})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    await house.run("lights_look", look="movie")
    await house.advance(seconds=10)
    for light in ("light.living_room_lamp", "light.living_room_ambient", "light.bedroom_lamp"):
        assert not house.is_on(light), light
    await house.run("lights_look", look="intermission")   # paused: enough to see by
    await house.advance(seconds=10)
    assert house.is_on("light.living_room_lamp") and house.is_on("light.living_room_ambient")


def lamp_steps(house, since):
    """The floor lamp's brightness commands after the given index into light_calls, in percent"""
    return [round(kw["brightness"] / 2.55) for e, on, kw in house.light_calls[since:]
            if e == "light.living_room_lamp" and on == "on" and "brightness" in kw]


async def test_calm_comes_the_hour_before_bed_and_blends_in(house_at):
    # Calm is an hour before the plan's bedtime (9:40, so 8:40), not a fixed time, on the curve, and
    # the printer's light steps down from Evening's 70 to Calm's 50 instead of jumping
    house = await house_at(f"{TUESDAY} 20:30", {"input_select.house_mode": "Evening", "sensor.bedtime_plan": PLAN})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    assert house.level("light.klipper_case_light") == 70
    await house.advance(minutes=9)                        # 8:39
    assert house.state("input_select.house_mode") == "Evening"
    await house.advance(minutes=1, seconds=30)            # 8:40:40
    assert house.state("input_select.house_mode") == "Calm"
    first = house.level("light.klipper_case_light")
    assert 60 < first < 70, f"one step, not the whole way: {first}"
    await house.advance(minutes=15)
    assert house.level("light.klipper_case_light") == 50
    assert house.attr("light.living_room_lamp", "color_mode") == "color_temp", "no amber"
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") >= 2700


async def test_nothing_goes_below_2700_k(house_at):
    # under 2700 K a lot of colour lamps mix in red and lose most of their light
    house = await house_at(f"{TUESDAY} 23:00", {"input_select.house_mode": "Calm", "sensor.bedtime_plan": PLAN})
    for look in ("evening", "calm", "intermission", "welcome"):
        await house.run("lights_look", look=look)
        await house.advance(seconds=10)
        assert house.attr("light.living_room_lamp", "color_mode") == "color_temp", look
        assert house.attr("light.living_room_lamp", "color_temp_kelvin") >= 2700, look
    await house.run("light_set", entity="light.living_room_lamp", level=30, kelvin=2200, priority=3)
    await house.advance(seconds=5)
    assert house.attr("light.living_room_lamp", "color_temp_kelvin") == 2700


async def test_blending_steps_are_too_small_to_see(house_at):
    # dusk with the floor lamp on a sunny day's 50%: Evening by the clock wants 78, and gets there a
    # step a minute, none bigger than 5% of where the lamp is (or 2 points)
    sunny = {"input_select.house_mode": "Day", "sensor.bedtime_plan": PLAN,
             "sun.sun": ("above_horizon", {"elevation": 50}), "weather.forecast_home": ("sunny", {"cloud_coverage": 0})}
    house = await house_at(f"{TUESDAY} 13:00", sunny)
    await house.run("lights_look", look="day")
    await house.advance(seconds=10)
    assert house.level("light.living_room_lamp") == 50
    since = len(house.light_calls)
    house.set("sun.sun", "above_horizon", elevation=2)      # the curve now says 78
    await house.settle()
    await house.advance(minutes=20)
    assert house.state("input_select.house_mode") == "Evening"
    steps = [50] + lamp_steps(house, since)
    assert len(steps) > 5, steps
    for a, b in zip(steps, steps[1:]):
        assert abs(b - a) <= max(2, a * 0.05) + 1, steps   # + 1 for rounding
    assert house.level("light.living_room_lamp") >= 76, "the curve at 2 degrees of sun says 78"


async def test_a_hand_on_a_dimmer_mid_fade_is_still_a_hand(house_at):
    # with a minute-long fade nearly every minute, "anything goes during a fade" would have hidden
    # every hand on a dimmer. On the way from where it was to where it's going is the house
    house = await house_at(f"{TUESDAY} 18:00", {"input_select.house_mode": "Day"})
    await house.run("light_set", entity="light.living_room_lamp", level=30, fade=2)
    await house.advance(seconds=20)
    await house.run("light_set", entity="light.living_room_lamp", level=80, fade=60)
    await house.advance(seconds=5)
    house.report("light.living_room_lamp", "on", 50)        # fading up from 30: on the way
    await house.advance(seconds=5)
    assert not manual(house, "light.living_room_lamp")
    house.by_hand("light.living_room_lamp", "on", 100)      # nowhere on the way from 30 to 80
    await house.settle()
    assert manual(house, "light.living_room_lamp")


async def test_the_bedroom_overhead_stands_in_for_a_dead_lamp(house_at):
    # a layer is what a light is doing: with the bedroom lamp's plug dead, the overhead gives the
    # bedroom its ambient light, low in its own range, instead of leaving the room dark
    house = await house_at(f"{TUESDAY} 19:00", {"input_select.house_mode": "Evening"})
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    assert not house.is_on("light.bedroom_light"), "the lamp works, the overhead stays off"
    house.set("light.bedroom_lamp", "unavailable")
    await house.run("lights_look", look="evening")
    await house.advance(seconds=10)
    assert house.is_on("light.bedroom_light")
    assert 1 <= house.level("light.bedroom_light") <= 15
