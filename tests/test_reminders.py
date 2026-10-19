"""Reminders (packages/reminders.yaml): set, kept, said and sent when they're due."""

TUESDAY = "2026-10-13"


async def test_a_reminder_goes_off_on_time(house_at):
    house = await house_at(f"{TUESDAY} 21:47", {"input_select.house_mode": "Evening"})
    await house.run("remind_me", message="to disconnect the car", minutes=60)
    assert house.state("sensor.reminders") == "1"
    await house.advance(minutes=59)
    assert not house.phoned("disconnect the car")
    await house.advance(minutes=2)
    assert house.phoned("A reminder: disconnect the car")
    assert house.said("disconnect the car")
    assert house.state("sensor.reminders") == "0"


async def test_two_reminders_keep_their_order(house_at):
    house = await house_at(f"{TUESDAY} 12:00")
    await house.run("remind_me", message="call the garage", minutes=30)
    await house.run("remind_me", message="feed the printer", minutes=10)
    assert house.attr("sensor.reminders", "next").startswith("feed the printer")
    await house.advance(minutes=12)
    assert house.phoned("feed the printer") and not house.phoned("call the garage")
