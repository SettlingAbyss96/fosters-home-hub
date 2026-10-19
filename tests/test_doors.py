"""The doors inside (packages/vacuum.yaml, estimates.yaml): the vacuum goes where it can, the bathroom
isn't empty with its door shut and the light on, and the bedroom door opening in the morning is
someone walking out."""

TUESDAY = "2026-10-13"


def cleaned(house):
    return [(c.service, c.data.get("cleaning_area_id")) for c in house.calls if c.domain == "vacuum"
            and c.service in ("start", "clean_area")]


async def test_the_vacuum_skips_a_shut_bedroom(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"binary_sensor.bedroom_door": "off", "binary_sensor.bathroom_door": "on"})
    await house.run("vacuum_clean")
    (service, areas), = cleaned(house)
    assert service == "clean_area"
    assert "bedroom" not in areas and "kitchen" in areas and "bathroom" in areas


async def test_all_doors_open_is_a_whole_clean(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"binary_sensor.bedroom_door": "on", "binary_sensor.bathroom_door": "on"})
    await house.run("vacuum_clean")
    assert cleaned(house) == [("start", None)]


async def test_a_door_sensor_not_answering_counts_as_open(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"binary_sensor.bedroom_door": "unavailable", "binary_sensor.bathroom_door": "on"})
    await house.run("vacuum_clean")
    assert cleaned(house) == [("start", None)]


async def test_leaving_says_which_room_it_skips(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"input_select.house_mode": "Day", "binary_sensor.bedroom_door": "off",
                                                "binary_sensor.bathroom_door": "on",
                                                "sensor.robot_vacuum_battery": "90",
                                                "sensor.robot_vacuum_last_clean_end": "2026-10-11T10:00:00+00:00"})
    await house.hass.services.async_call("input_select", "select_option",
                                         {"entity_id": "input_select.vacuum_when_leaving", "option": "Always"}, blocking=True)
    house.set("person.resident", "not_home")
    house.set("sensor.phone_ssid", "Not Connected")
    await house.advance(minutes=4)
    assert house.state("input_select.house_mode") == "Away"
    assert cleaned(house)[0][0] == "clean_area"
    assert house.phoned("not the bedroom")


async def test_the_bathroom_is_occupied_with_its_door_shut_and_the_light_on(house_at):
    house = await house_at(f"{TUESDAY} 07:00", {"binary_sensor.bathroom_door": "off"})
    await house.run("light_set", entity="light.bathroom_light", level=100)
    assert house.state("binary_sensor.bathroom_occupied") == "on"
    house.set("binary_sensor.bathroom_door", "on")
    await house.settle()
    assert house.state("binary_sensor.bathroom_occupied") == "off", "light left on, door open: nobody"


async def test_dozing_off_never_switches_off_someone_in_the_bathroom(house_at):
    house = await house_at(f"{TUESDAY} 23:00", {"input_select.house_mode": "Night", "input_boolean.phone_on_charger": "on",
                                                "binary_sensor.bathroom_door": "off", "binary_sensor.bedroom_door": "on"})
    await house.run("light_set", entity="light.bedroom_lamp", level=100)
    await house.run("light_set", entity="light.bathroom_light", level=100)
    house.set("sensor.last_sign_of_life", house.now().isoformat())
    await house.advance(minutes=90)
    assert not house.is_on("light.bedroom_lamp")
    assert house.is_on("light.bathroom_light")


async def test_walking_out_of_the_bedroom_stops_the_alarm(house_at):
    house = await house_at(f"{TUESDAY} 04:50", {"input_select.house_mode": "Night", "binary_sensor.bedroom_door": "off"})
    await house.advance(minutes=37)                      # 5:27, good morning said
    assert house.said("Good morning")
    house.forget()
    house.set("binary_sensor.bedroom_door", "on")
    await house.settle()
    assert house.attr("sensor.seen_up", "how") == "out of the bedroom"
    await house.advance(minutes=15)
    assert not house.said("Time to get up")


async def test_the_bedroom_door_at_night_isnt_up(house_at):
    house = await house_at(f"{TUESDAY} 02:00", {"input_select.house_mode": "Night", "binary_sensor.bedroom_door": "off"})
    before = house.state("sensor.seen_up")
    house.set("binary_sensor.bedroom_door", "on")
    await house.settle()
    assert house.state("sensor.seen_up") == before


async def test_on_the_way_home_gets_the_house_ready(house_at):
    house = await house_at(f"{TUESDAY} 17:30", {"input_select.house_mode": "Away", "person.resident": "not_home",
                                                "sensor.phone_ssid": "Not Connected",
                                                "vacuum.robot_vacuum": "cleaning",
                                                "sensor.home_resident_distance": ("12000", {"unit_of_measurement": "ft"}),
                                                "sensor.home_resident_direction_of_travel": "towards"})
    await house.settle()
    assert house.state("timer.arrival_window") == "idle", "3.7 km out is still too far"
    house.set("sensor.home_resident_distance", "5000")    # 1.5 km
    await house.settle()
    assert house.state("timer.arrival_window") == "active"
    assert house.called("vacuum.return_to_base")


async def test_vacuum_later_goes_on_time_and_minds_the_doors(house_at):
    house = await house_at(f"{TUESDAY} 14:00", {"binary_sensor.bedroom_door": "off", "binary_sensor.bathroom_door": "on"})
    await house.run("vacuum_later", minutes=15)
    assert house.state("timer.vacuum_later") == "active"
    await house.advance(minutes=14)
    assert cleaned(house) == []
    await house.advance(minutes=2)
    (service, areas), = cleaned(house)
    assert service == "clean_area" and "bedroom" not in areas
