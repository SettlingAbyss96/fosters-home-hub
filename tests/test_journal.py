"""How did it go? The journal on the Hub (hub/hub_journal.py) working out where you stayed and what
to ask, and the house asking it after the welcome home (packages/journal.yaml). The places are made
up, somewhere around 40° N, and the positions go straight in the way Home Assistant posts them."""

import math
import pathlib
import re
import sys
from datetime import datetime, timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hub"))
import hub_journal as j  # noqa: E402

HOME = (40.0, -75.0)
NOW = datetime(2026, 10, 27, 18, 30).timestamp()      # a Tuesday evening
DAY = j.DAY


def at(north_m, east_m):
    """A point so many metres north and east of home"""
    return HOME[0] + north_m / 111320, HOME[1] + east_m / (111320 * math.cos(math.radians(HOME[0])))


WORK = at(15000, 6000)
CAFE = at(2000, -1500)
SHOPS = at(-3000, 2500)


def the_map(db):
    pois = [("n1", *CAFE, "Lamplight Coffee", "cafe", "amenity=cafe"),
            ("n2", *at(-3000, 2530), "Corner Pharmacy", "health", "amenity=pharmacy"),
            ("w3", *at(-3050, 2500), "Fresh Market", "grocery", "shop=supermarket"),
            ("n4", *at(5000, 5000), "Fuel Stop", "errand", "amenity=fuel"),
            ("n5", *at(9000, -2000), "The Long Table", "restaurant", "amenity=restaurant")]
    # a crowded block: a dozen places within 60 m of each other
    pois += [(f"n{100 + k}", *at(-6000 + 15 * (k % 4), 8000 + 15 * (k // 4)), f"Shop {k}", "shop", "shop=clothes")
             for k in range(12)]
    db.executemany("INSERT OR REPLACE INTO pois VALUES (?, ?, ?, ?, ?, ?)", pois)
    db.commit()


def setup(tmp_path):
    cfg = j.load_config(REPO / "hub" / "journal.example.toml")
    db = j.connect(str(tmp_path / "journal.db"))
    the_map(db)
    for k in range(10):                                  # home, so it knows where home is
        point(db, NOW - 3 * DAY + k * 60, HOME, zone="home")
    return cfg, db


def point(db, t, where, zone="not_home", acc=5, aoi=None):
    j.add_point(db, {"t": t, "lat": where[0], "lon": where[1], "acc": acc, "zone": zone, "aoi": aoi})


def trip(db, start, stops, acc=5):
    """Leave home at `start`, then for each (where, minutes, zone, aoi) one position on arrival and
    the next one at the next place, the way iOS reports, and home at the end"""
    t = start
    point(db, t, HOME, zone="home")
    t += 60
    for where, minutes, zone, aoi in stops:
        t += 15 * 60                                     # the drive there
        point(db, t, where, zone=zone or "not_home", acc=acc, aoi=aoi)
        t += minutes * 60
    t += 15 * 60
    point(db, t, HOME, zone="home")
    return t


# -- stays ------------------------------------------------------------------------------------
def test_one_position_and_then_the_next_place_is_a_stay(tmp_path):
    cfg, db = setup(tmp_path)
    t0 = NOW - 4 * 3600
    point(db, t0, CAFE)
    point(db, t0 + 50 * 60, SHOPS)                       # 50 minutes later, 5.9 km away
    point(db, t0 + 80 * 60, HOME, zone="home")
    pts = [dict(r) for r in db.execute("SELECT * FROM points WHERE t >= ? ORDER BY t", (t0,))]
    found = j.stays(pts, cfg, HOME)
    assert len(found) == 2
    cafe = found[0]
    trip_there = j.dist(*CAFE, *SHOPS) / cfg["stays"]["travel_mps"]
    assert abs(cafe["end"] - (t0 + 50 * 60 - trip_there)) < 1, "it ended about as long before as the trip took"


def test_a_stop_and_home_itself_arent_stays(tmp_path):
    cfg, db = setup(tmp_path)
    t0 = NOW - 4 * 3600
    point(db, t0, at(300, 0))                            # 300 m out: the GPS wandering at home
    point(db, t0 + 40 * 60, CAFE)
    point(db, t0 + 44 * 60, SHOPS)                       # four minutes at the cafe: a stop
    point(db, t0 + 90 * 60, HOME, zone="home")
    pts = [dict(r) for r in db.execute("SELECT * FROM points WHERE t >= ? ORDER BY t", (t0,))]
    assert [round(j.dist(s["lat"], s["lon"], *SHOPS)) for s in j.stays(pts, cfg, HOME)] == [0]


# -- places -----------------------------------------------------------------------------------
def test_the_place_is_the_one_its_most_likely_to_be(tmp_path):
    cfg, db = setup(tmp_path)
    near = j.near_pois(db, *at(2008, -1500), 5)
    assert near[0][2]["name"] == "Lamplight Coffee" and near[0][0] > 0.9
    # between the pharmacy and the supermarket with a good fix: the pharmacy's door is 2 m away
    near = j.near_pois(db, *at(-3000, 2528), 5)
    assert near[0][2]["name"] == "Corner Pharmacy" and near[0][0] >= j.SURE


def test_a_crowded_block_with_a_poor_fix_is_nowhere_in_particular(tmp_path):
    cfg, db = setup(tmp_path)
    s = {"zone": None, "lat": at(-5980, 8020)[0], "lon": at(-5980, 8020)[1], "acc": 40, "aoi": None}
    near = j.near_pois(db, s["lat"], s["lon"], s["acc"])
    assert len(near) >= 6 and near[0][0] < j.SURE, "a dozen shops, none of them likely"
    pid = j.place_for(db, cfg, s)
    assert db.execute("SELECT name, kind FROM places WHERE id = ?", (pid,)).fetchone()["kind"] is None
    # the same with Apple saying it's a market: the market
    pid = j.place_for(db, cfg, dict(s, aoi="Riverside Market"))
    row = db.execute("SELECT name, kind FROM places WHERE id = ?", (pid,)).fetchone()
    assert (row["name"], row["kind"]) == ("Riverside Market", "area")


def test_the_maps_tags_make_kinds(tmp_path):
    text = ("node\t1\t40.1\t-75.1\tLamplight Coffee\tcafe\t\t\t\t\n"
            "way\t2\t40.2\t-75.2\tBean There\t\tcoffee\t\t\t\n"
            "node\t3\t40.3\t-75.3\tCorner Pharmacy\tpharmacy\t\t\t\t\n"
            "node\t4\t40.4\t-75.4\tGizmo World\t\tcomputer\t\t\t\n"
            "node\t5\t40.5\t-75.5\tRiverside Park\t\t\tpark\t\t\n"
            "node\t6\t40.6\t-75.6\t\tcafe\t\t\t\t\n")                  # no name: not a place
    pois = j.parse_pois(text)
    assert [(p[0], p[4]) for p in pois] == [("n1", "cafe"), ("w2", "cafe"), ("n3", "health"), ("n4", "shop"),
                                             ("n5", "outdoors")]


# -- what gets asked --------------------------------------------------------------------------
def test_work_and_a_new_cafe_in_one_question_work_first(tmp_path):
    cfg, db = setup(tmp_path)
    trip(db, NOW - 11 * 3600, [(WORK, 480, "Work", None), (CAFE, 45, None, None)])
    q = j.ask(db, cfg, now=NOW, rng=__import__("random").Random(1))
    assert [p["kind"] for p in q["places"]] == ["work", "cafe"]
    work_qs = cfg["kinds"]["work"]["again"]
    assert any(q["question"].startswith(w) for w in work_qs)
    assert "Lamplight Coffee" in q["question"] and q["places"][1]["first"]


def test_never_the_pharmacy_the_petrol_station_or_nowhere(tmp_path):
    cfg, db = setup(tmp_path)
    trip(db, NOW - 5 * 3600, [(at(-3000, 2530), 25, None, None), (at(5000, 5000), 20, None, None),
                              (at(-12000, -9000), 90, None, None)])     # someone's house: not on the map
    assert j.ask(db, cfg, now=NOW) == {}


def test_somewhere_familiar_only_after_a_while(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 20 * DAY, [(CAFE, 60, None, None)])
    q = j.ask(db, cfg, now=end + 600)
    j.answer(db, cfg, q["ask"], "Lovely, quiet, good flat white.", now=end + 900)
    end = trip(db, NOW - 17 * DAY, [(CAFE, 60, None, None)])
    assert j.ask(db, cfg, now=end + 600) == {}, "three days on: not again yet"
    end = trip(db, NOW - 2 * DAY, [(CAFE, 60, None, None)])
    q = j.ask(db, cfg, now=end + 600)
    assert q and not q["places"][0]["first"], "18 days on (again_days 14): asked, as somewhere familiar"
    assert any(q["question"] == t.format(name="Lamplight Coffee") for t in cfg["kinds"]["cafe"]["again"])


def test_the_weekly_shop_only_the_first_time(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 8 * DAY, [(at(-3050, 2500), 30, None, None)])
    q = j.ask(db, cfg, now=end + 600)
    assert q["places"][0]["name"] == "Fresh Market"
    j.answer(db, cfg, q["ask"], "Fine, pricey.", now=end + 700)
    end = trip(db, NOW - 3600 * 3, [(at(-3050, 2500), 30, None, None)])
    assert j.ask(db, cfg, now=end + 600) == {}


def test_work_once_a_day(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 11 * 3600, [(WORK, 240, "Work", None)])
    q = j.ask(db, cfg, now=end + 300)
    j.answer(db, cfg, q["ask"], "Good, shipped it.", now=end + 400)
    end = trip(db, end + 600, [(WORK, 60, "Work", None)])             # back in for an hour
    assert j.ask(db, cfg, now=end + 300) == {}


def test_said_nothing_is_asked_all_the_same_and_unheard_comes_round_again(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 5 * 3600, [(at(9000, -2000), 70, None, None), (CAFE, 30, None, None)])
    q = j.ask(db, cfg, now=end + 60)
    j.answer(db, cfg, q["ask"], "", heard=False, now=end + 90)
    again = j.ask(db, cfg, now=end + 120)
    assert again["question"] and {p["name"] for p in again["places"]} == {p["name"] for p in q["places"]}
    j.answer(db, cfg, again["ask"], "", heard=True, now=end + 150)
    assert j.ask(db, cfg, now=end + 180) == {}, "asked, not answered: done"
    assert db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_an_answer_is_kept_and_the_rest_of_the_trip_doesnt_turn_up_tomorrow(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 12 * 3600, [(WORK, 420, "Work", None), (at(9000, -2000), 60, None, None),
                                     (CAFE, 30, None, None)])
    q = j.ask(db, cfg, now=end + 60)
    assert len(q["places"]) == 2, "two at most"
    out = j.answer(db, cfg, q["ask"], "Long meeting, then a good dinner.", now=end + 120)
    assert out["kept"]
    e = j.journal(db, now=end + 200)
    assert len(e) == 1 and e[0]["answer"] == "Long meeting, then a good dinner." and e[0]["places"]
    assert j.ask(db, cfg, now=end + 3600) == {}, "the third place went with the trip"


def test_never_the_same_question_three_times_running(tmp_path):
    cfg, db = setup(tmp_path)
    seen = []
    for d in range(6):
        end = trip(db, NOW - (10 - d) * DAY, [(WORK, 300, "Work", None)])
        q = j.ask(db, cfg, now=end + 60)
        j.answer(db, cfg, q["ask"], "Fine.", now=end + 90)
        seen.append(q["question"])
    for k in range(3, len(seen)):
        assert seen[k] not in seen[k - 3:k]


def test_history_from_the_location_log_is_familiar_and_never_asked(tmp_path):
    cfg, db = setup(tmp_path)
    log = tmp_path / "iphone.csv"
    t0 = NOW - 20 * DAY
    rows = ["Home Assistant notifications (Log started: 2026-10-10T17:42:47+00:00)", "-" * 40,
            "time,zone,latitude,longitude,accuracy_m,speed,altitude_m,address"]
    for t, where, zone in [(t0, HOME, "home"), (t0 + 1200, CAFE, "not_home"), (t0 + 4800, HOME, "home")]:
        rows.append(f"{datetime.fromtimestamp(t).astimezone().isoformat(timespec='seconds')},{zone},{where[0]},{where[1]},5,,,\"\"")
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert j.import_csv(db, str(log)) == 3
    j.refresh_visits(db, cfg, NOW, history=True)
    assert j.ask(db, cfg, now=t0 + 5000) == {}, "history isn't a trip"
    end = trip(db, NOW - 3600 * 4, [(CAFE, 40, None, None)])
    assert j.ask(db, cfg, now=end + 60)["places"][0]["first"] is False, "been before, in the log"


def test_today_reads_back_as_one_paragraph(tmp_path):
    cfg, db = setup(tmp_path)
    end = trip(db, NOW - 11 * 3600, [(WORK, 420, "Work", None)])
    q = j.ask(db, cfg, now=end + 60)
    j.answer(db, cfg, q["ask"], "Good. The demo worked", now=end + 90)
    j.note(db, "Ordered the new nozzle", now=end + 300)
    assert j.today(db, now=end + 400) == {"n": 2, "text": "About Work: Good. The demo worked. A note: Ordered the new nozzle."}


def test_no_question_says_how_long_i_was_anywhere():
    # Jarvis never comments on work hours, and two hours in a cafe is nobody's business
    cfg = j.load_config(REPO / "hub" / "journal.example.toml")
    for kind, k in cfg["kinds"].items():
        for which in ("first", "again", "also"):
            for t in k.get(which, []):
                assert not re.search(r"\b(hours?|minutes?|long|late|early|all day|so soon)\b", t, re.I), (kind, t)


# -- the house asking -------------------------------------------------------------------------
TUESDAY = "2026-10-13"
ASK = {"status": 200, "content": {"ask": 7, "question": "How was work? And Lamplight Coffee, how was the ambiance?",
                                  "places": [{"name": "Work", "kind": "work", "first": False, "minutes": 480},
                                             {"name": "Lamplight Coffee", "kind": "cafe", "first": True, "minutes": 45}]}}


def answers(*sentences):
    return [{"id": None, "sentence": s, "slots": {}} if isinstance(s, str) else s for s in sentences]


async def welcome(house):
    """The welcome home, with its words ready, and then whatever comes after it"""
    house.hass.bus.async_fire("welcome_home_words", {"text": "Welcome home. A quiet day in the markets.", "kit": ""})
    await house.settle()
    await house.hass.services.async_call("script", "turn_on", {"entity_id": "script.welcome_home"})
    await house.advance(seconds=10)
    assert house.said("A quiet day in the markets")


async def test_after_the_welcome_jarvis_asks_how_it_went_and_keeps_it(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Evening"})
    house.replies["rest_command.journal_ask"] = ASK
    house.replies["assist_satellite.ask_question"] = answers(
        "Good, we shipped the release.", "The coffee place was cosy, too loud to work though.",
        {"id": "done", "sentence": "no that's it", "slots": {}})
    await welcome(house)
    asked = house.called("assist_satellite.ask_question")
    assert asked[0].data["question"] == ASK["content"]["question"]
    assert asked[1].data["question"].startswith("Anything"), "a sentence ends the turn, so it asks for more"
    kept = house.called("rest_command.journal_answer")
    assert len(kept) == 1 and kept[0].data["ask"] == 7 and kept[0].data["heard"]
    assert kept[0].data["answer"] == "Good, we shipped the release. The coffee place was cosy, too loud to work though."
    line = house.called("notify.send_message", entity_id="notify.journal_log")
    assert line and "Work and Lamplight Coffee" in line[0].data["message"] and "shipped the release" in line[0].data["message"]
    assert any(house.said(w) for w in ("Noted.", "Written down.", "In the journal.", "Duly noted."))
    shown = house.attr("sensor.journal", "entries")
    assert shown[-1]["places"] == "Work and Lamplight Coffee" and "too loud to work" in shown[-1]["answer"], "on the Routines page"


async def test_not_now_is_an_answer(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Evening"})
    house.replies["rest_command.journal_ask"] = ASK
    house.replies["assist_satellite.ask_question"] = answers({"id": "skip", "sentence": "not now", "slots": {}})
    await welcome(house)
    kept = house.called("rest_command.journal_answer")
    assert kept[0].data["answer"] == "" and kept[0].data["heard"], "asked, so it doesn't come round again"
    assert len(house.called("assist_satellite.ask_question")) == 1
    assert house.said("Of course.")
    assert not house.called("notify.send_message", entity_id="notify.journal_log")


@pytest.mark.expect_errors("No answer from question")
@pytest.mark.expect_errors("busy")
async def test_silence_after_the_question_is_asked_and_a_busy_satellite_isnt(house_at):
    house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Evening"})
    house.replies["rest_command.journal_ask"] = ASK

    def listened_to_nothing(call):
        house.freezer.tick(timedelta(seconds=12))      # the question, then listening, then nothing
        return HomeAssistantError("No answer from question")

    house.replies["assist_satellite.ask_question"] = listened_to_nothing
    await welcome(house)
    assert house.called("rest_command.journal_answer")[0].data["heard"]
    house.forget()
    await house.advance(minutes=1)
    house.replies["assist_satellite.ask_question"] = HomeAssistantError("busy")
    await house.run("journal_ask")
    assert not house.called("rest_command.journal_answer")[0].data["heard"], "never said: next time"


async def test_no_questions_with_guests_in_at_night_or_switched_off(house_at):
    for state in ({"input_boolean.guest_mode": "on"}, {"input_select.house_mode": "Night"},
                  {"input_boolean.auto_journal": "off"}, {"input_boolean.jarvis_muted": "on"}):
        house = await house_at(f"{TUESDAY} 19:30", {"input_select.house_mode": "Evening", **state})
        house.replies["rest_command.journal_ask"] = ASK
        await house.run("journal_ask")
        await house.advance(seconds=5)
        assert not house.called("assist_satellite.ask_question"), state
        assert not house.called("rest_command.journal_ask"), state


async def test_ask_me_about_my_day_works_even_switched_off(house_at):
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Evening", "input_boolean.auto_journal": "off"})
    house.replies["rest_command.journal_ask"] = ASK
    house.replies["assist_satellite.ask_question"] = answers("Fine.", {"id": "done", "sentence": "no", "slots": {}})
    assert await house.ask("JournalAskMe") == "Of course."
    assert not house.called("assist_satellite.ask_question"), "not over the top of its own answer"
    await house.advance(seconds=6)
    assert house.called("assist_satellite.ask_question")
    assert house.called("rest_command.journal_answer")[0].data["answer"] == "Fine."


async def test_ask_me_with_nothing_to_ask_says_so(house_at):
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Evening"})
    await house.ask("JournalAskMe")
    await house.advance(seconds=6)
    assert house.said("Nothing I'd ask about today")
    assert not house.called("assist_satellite.ask_question")


async def test_a_note_and_todays_journal_by_voice(house_at):
    house = await house_at(f"{TUESDAY} 21:00", {"input_select.house_mode": "Evening"})
    said = await house.ask("JournalNote", note="the new nozzle prints PETG beautifully")
    assert said in ("Noted.", "Written down.", "In the journal.")
    assert house.called("rest_command.journal_note")[0].data["text"] == "the new nozzle prints PETG beautifully"
    assert "PETG beautifully" in house.called("notify.send_message", entity_id="notify.journal_log")[0].data["message"]
    assert house.attr("sensor.journal", "entries")[-1]["answer"] == "the new nozzle prints PETG beautifully"
    house.replies["rest_command.journal_today"] = {"status": 200, "content": {"n": 1, "text": "A note: the new nozzle prints PETG beautifully."}}
    assert await house.ask("JournalToday") == "A note: the new nozzle prints PETG beautifully."
    house.replies["rest_command.journal_today"] = {"status": 200, "content": {"n": 0, "text": ""}}
    assert await house.ask("JournalToday") == "Nothing in the journal today yet."


async def test_every_position_goes_to_the_journal(house_at):
    house = await house_at(f"{TUESDAY} 12:00", {"input_select.house_mode": "Away",
                                                "person.resident": ("not_home", {"latitude": 40.0, "longitude": -75.0}),
                                                "sensor.phone_geocoded_location": ("Somewhere", {"Areas Of Interest": "Riverside Market"})})
    house.forget()
    house.set("person.resident", "not_home", latitude=40.01, longitude=-75.02, gps_accuracy=6)
    await house.settle()
    sent = house.called("rest_command.journal_point")
    assert len(sent) == 1
    p = sent[0].data["point"]
    assert (p["lat"], p["lon"], p["zone"], p["aoi"]) == (40.01, -75.02, "not_home", "Riverside Market")
