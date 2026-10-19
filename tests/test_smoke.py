"""The bench itself: everything loads, and the plan for a Tuesday says 5:25."""


async def test_loads(house_at):
    house = await house_at("2026-10-13 04:30", {"input_select.house_mode": "Night"})
    await house.advance(minutes=2)
    assert house.state("input_boolean.auto_vacuum") == "on"
    assert house.attr("sensor.bedtime_plan", "wake").startswith("2026-10-13T05:25")
    assert house.state("sensor.next_wake_up").startswith("5:25 today")
