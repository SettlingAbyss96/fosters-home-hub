"""The asleep filter (packages/estimates.yaml). The numbers are first guesses until the Oura nights
tune them, so these check the shape of it: it takes a while, it has memory, it wakes up for a
real sign of life and not for a phone finishing its charge."""

TUESDAY = "2026-10-13"
NIGHT = {"input_select.house_mode": "Night", "input_boolean.phone_on_charger": "on"}


async def quiet_since(house):
    house.set("sensor.last_sign_of_life", house.now().isoformat())
    await house.settle()


async def test_falls_asleep_after_goodnight(house_at):
    house = await house_at(f"{TUESDAY} 23:20", NIGHT)
    await quiet_since(house)
    await house.advance(minutes=5)
    assert house.state("binary_sensor.asleep") == "off", "not straight away"
    await house.advance(minutes=30)
    assert house.state("binary_sensor.asleep") == "on"


async def test_a_trip_to_the_bathroom_wakes_it_then_it_settles_again(house_at):
    house = await house_at(f"{TUESDAY} 23:20", NIGHT)
    await quiet_since(house)
    await house.advance(minutes=60)
    assert house.state("binary_sensor.asleep") == "on"
    for _ in range(3):
        house.set("binary_sensor.hub_500_motion", "on")
        await house.advance(seconds=40)
        house.set("binary_sensor.hub_500_motion", "off")
        await house.advance(seconds=20)
    assert house.state("binary_sensor.asleep") == "off"
    await house.advance(minutes=40)
    assert house.state("binary_sensor.asleep") == "on"


async def test_the_phone_finishing_its_charge_isnt_anyone(house_at):
    house = await house_at(f"{TUESDAY} 23:20", NIGHT)
    await quiet_since(house)
    house.set("sensor.phone_battery_state", "Charging")
    await house.advance(minutes=60)
    before = house.state("sensor.last_sign_of_life")
    house.set("sensor.phone_battery_state", "Full")
    await house.advance(minutes=2)
    assert house.state("sensor.last_sign_of_life") == before
    assert house.state("binary_sensor.asleep") == "on"


async def test_typing_isnt_sleeping(house_at):
    house = await house_at(f"{TUESDAY} 23:20", NIGHT)
    await quiet_since(house)
    house.set("binary_sensor.at_the_desk", "on")
    await house.advance(minutes=90)
    assert house.state("binary_sensor.asleep") == "off"


async def test_a_quiet_afternoon_isnt_sleep(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day"})
    await quiet_since(house)
    await house.advance(minutes=120)
    assert house.state("binary_sensor.asleep") == "off"


async def test_away_is_never_asleep(house_at):
    house = await house_at(f"{TUESDAY} 23:20", {"input_select.house_mode": "Away", "person.resident": "not_home",
                                                 "sensor.phone_ssid": "Somewhere else"})
    await quiet_since(house)
    await house.advance(minutes=90)
    assert float(house.state("sensor.asleep_belief")) < 1


async def test_dozing_off_with_the_lamp_on_turns_it_off(house_at):
    house = await house_at(f"{TUESDAY} 23:00", NIGHT)
    await house.run("light_set", entity="light.bedroom_lamp", level=100)
    await house.run("light_set", entity="light.living_room_lamp", level=60)
    await quiet_since(house)
    await house.advance(minutes=90)
    assert not house.is_on("light.bedroom_lamp")
    assert not house.is_on("light.living_room_lamp")
    assert house.phoned("dozed off")


async def test_the_desk_counts_when_its_in_use_and_doesnt_chatter(house_at):
    # four days of the desk plug: 55 to 95 W in use, 35 to 40 W locked and charging
    house = await house_at(f"{TUESDAY} 21:00", {"sensor.computer_session_state": "unavailable", "sensor.desk_power": "18"})
    for watts, at_desk in ((38, "off"), (68, "on"), (47, "on"), (44, "off"), (39, "off"), (52, "on")):
        house.set("sensor.desk_power", str(watts))
        await house.advance(seconds=5, step=1)
        assert house.state("binary_sensor.at_the_desk") == at_desk, f"{watts} W ({house.attr('binary_sensor.at_the_desk', 'desk_watts')})"


async def test_a_computer_charging_on_the_desk_isnt_typing(house_at):
    # home late to the Calm look, straight to bed without goodnight, the laptop locked and charging
    # with its agent gone, the desk wobbling around 35 to 40 W. With the line too low it reads as
    # typing every few seconds, the house never decides anyone's asleep, and the lights burn until
    # morning. With it right, it says asleep in a couple of hours
    house = await house_at("2026-10-14 00:53", {"input_select.house_mode": "Calm",
                                                "sensor.computer_session_state": "unavailable", "sensor.desk_power": "38"})
    await house.run("lights_look", look="calm")
    assert house.is_on("light.bedroom_lamp")
    await quiet_since(house)
    for minute in range(150):
        house.set("sensor.desk_power", str((36, 39, 35.5, 40, 37.5)[minute % 5]))
        await house.advance(minutes=1)
    assert house.state("binary_sensor.at_the_desk") == "off"
    assert not house.is_on("light.bedroom_lamp"), "dozed off with the lights on, by 3:23"
    assert not house.is_on("light.living_room_lamp")
