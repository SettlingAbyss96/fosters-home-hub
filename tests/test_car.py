"""The car and idle fees (packages/car.yaml). A public charger bills by the minute once the car has
stopped charging and is still plugged in."""

TUESDAY = "2026-10-13"
DONE = "chargePurposeReachedAndNotConservationCharging"
# bed 9:40 PM, nudge 9:10 PM, up 5:25 AM
PLAN = ("2026-10-14T01:40:00+00:00", {"wake": "2026-10-14T09:25:00+00:00", "nudge_at": "2026-10-14T01:10:00+00:00"})


def charging(done_at: str, battery: int = 60) -> dict:
    return {"binary_sensor.car_plugged_in": "on", "sensor.car_charging_state": "charging",
            "sensor.car_battery": str(battery),
            "sensor.car_charging_done_at": (done_at, {"device_class": "timestamp"})}


def reminders(house):
    return [c for c in house.phoned() if c.data.get("title") == "Car" and c.data.get("message") != "clear_notification"]


async def test_a_finished_charge_still_plugged_in_keeps_reminding_until_its_unplugged(house_at):
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening", **charging("2026-10-14T03:00:00+00:00")})
    house.set("sensor.car_battery", "80")
    house.set("sensor.car_charging_state", DONE)
    await house.advance(seconds=10)
    assert len(reminders(house)) == 1
    assert "80%" in reminders(house)[0].data["message"]
    assert reminders(house)[0].data["data"]["push"]["interruption-level"] == "time-sensitive"
    assert house.said("done charging"), "home and up: out loud too"
    await house.advance(minutes=10)
    assert len(reminders(house)) == 2
    house.set("binary_sensor.car_plugged_in", "off")
    await house.advance(minutes=30)
    assert len(reminders(house)) == 2, "unplugged, so that's it"
    assert house.phoned("clear_notification")


async def test_plugged_in_without_a_session_is_left_alone(house_at):
    # plugged in, the session not started: no charge has ended, so no fee and nothing to say
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening", "binary_sensor.car_plugged_in": "on",
                                                "sensor.car_charging_state": "readyForCharging", "sensor.car_battery": "40"})
    house.set("sensor.car_charging_state", "notReadyForCharging")
    await house.advance(minutes=60)
    assert not reminders(house)


async def test_unplugged_and_snooze_from_the_notification(house_at):
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening", **charging("2026-10-14T03:00:00+00:00")})
    house.set("sensor.car_charging_state", DONE)
    await house.advance(seconds=10)
    house.hass.bus.async_fire("mobile_app_notification_action", {"action": "CAR_SNOOZE"})
    await house.advance(minutes=14)
    assert len(reminders(house)) == 1, "snoozed: nothing for 15 minutes from the tap"
    await house.advance(minutes=2)
    assert len(reminders(house)) == 2
    house.hass.bus.async_fire("mobile_app_notification_action", {"action": "CAR_UNPLUGGED"})
    await house.advance(minutes=30)
    assert len(reminders(house)) == 2


async def test_the_cars_own_estimate_starts_it_before_the_fetch_does(house_at):
    # Audi's data comes every 15 minutes, so the car's estimate is the earlier sign
    house = await house_at(f"{TUESDAY} 20:00", {"input_select.house_mode": "Evening", **charging("2026-10-14T00:20:00+00:00", 78)})
    await house.advance(minutes=19)
    assert not reminders(house)
    await house.advance(minutes=2)
    assert len(reminders(house)) == 1
    assert "about now" in reminders(house)[0].data["message"]


async def test_at_night_its_the_phone_not_the_hub(house_at):
    house = await house_at("2026-10-14 02:00", {"input_select.house_mode": "Night", **charging("2026-10-14T09:00:00+00:00")})
    house.set("sensor.car_charging_state", DONE)
    await house.advance(seconds=10)
    assert len(reminders(house)) == 1
    assert not house.said("done charging")


async def test_still_charging_past_bedtime_gets_said_at_the_nudge(house_at):
    # done at 1:40 AM with bed at 9:40 PM: said at the nudge, while there's still time to unplug it
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Evening", "sensor.bedtime_plan": PLAN,
                                                **charging("2026-10-14T05:40:00+00:00")})
    await house.advance(minutes=9)
    assert not house.said("after bedtime")
    await house.advance(minutes=2)
    assert house.said("charging until 1:40, after bedtime")


async def test_the_morning_after_says_its_still_plugged_in(house_at):
    house = await house_at("2026-10-14 02:00", {"input_select.house_mode": "Night", **charging("2026-10-14T09:00:00+00:00")})
    house.set("sensor.car_charging_state", DONE)
    await house.advance(minutes=200)                      # the reminders give up after three hours
    house.forget()
    await house.run("house_mode_set", mode="Morning")
    await house.advance(seconds=10)
    assert house.said("finished charging at 2:00")
