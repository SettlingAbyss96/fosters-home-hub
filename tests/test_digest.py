"""The digest behind the welcome home (hub/hub_digest.py): nothing said twice, a repo only ever
what's new since last time, and a different way of telling it each time. No network here, the
items go straight in the way a fetch would put them."""

import json
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hub"))
import hub_digest as d  # noqa: E402

NOW = 1792800000.0          # October 24, 2026
DAY = d.DAY


def config(*sources):
    cfg = d.load_config(REPO / "hub" / "digest.example.toml")
    cfg["sources"] = {}
    for s in sources:
        d.add_source(cfg, s)
    return cfg


def entry(title, days_ago=1.0, link=None, raw=""):
    link = link or f"https://example.com/{title.lower().replace(' ', '-')}"
    return {"guid": link, "link": link, "title": title, "raw": raw or f"All about {title}.", "when": NOW - days_ago * DAY}


def a_house(tmp_path):
    """A pool with plenty on every shelf, like the real one"""
    cfg = config(
        {"name": "Grant's", "shelf": "market", "kind": "feed", "url": "x"},
        {"name": "Doomberg", "shelf": "market", "kind": "feed", "url": "x"},
        {"name": "Kalico", "shelf": "printing", "kind": "commits", "repo": "KalicoCrew/kalico"},
        {"name": "Hackaday 3D", "shelf": "printing", "kind": "feed", "url": "x"},
        {"name": "r/klippers", "shelf": "printing", "kind": "forum", "url": "x"},
        {"name": "Orca forks", "shelf": "printing", "kind": "forks", "repo": "OrcaSlicer/OrcaSlicer"},
        {"name": "Robots", "shelf": "robotics_ai", "kind": "feed", "url": "x"},
        {"name": "Hackaday", "shelf": "wild", "kind": "feed", "url": "x"},
        {"name": "F1", "shelf": "f1", "kind": "feed", "url": "x"},
    )
    db = d.connect(str(tmp_path / "digest.db"))
    # headlines as different from each other as real ones are
    words = ("copper nickel yields credit refinery margins hotend nozzle macro probe gantry servo gripper "
             "lidar scope solder tyres pitstop wing biotech tariffs gilts shipping lithium plastics "
             "filament resin belts bearings encoder firmware kernel compiler").split()
    rng = random.Random(0)
    for name in ["Grant's", "Doomberg", "Hackaday 3D", "r/klippers", "Robots", "Hackaday", "F1"]:
        d.ingest(db, cfg["sources"][name], [entry(" ".join(rng.sample(words, 4)).capitalize(), days_ago=0.1 + k / 5)
                                            for k in range(12)], NOW)
    d.ingest(db, cfg["sources"]["Kalico"], [entry(f"stepper: change {k}", days_ago=k / 3, link=f"https://github.com/KalicoCrew/kalico/commit/{k}")
                                            for k in range(8)], NOW)
    return cfg, db


def say(db, cfg, now, rng, late=False):
    kit = d.draw(db, cfg, late=late, now=now, rng=rng)
    assert kit is not None
    d.tell(db, cfg, kit["kit"], f"Welcome home, sir. {kit['format']} at {now}.", now=now)
    return kit


def ids_in(db, kit):
    return [i for s in json.loads(db.execute("SELECT slots FROM kits WHERE id = ?", (kit["kit"],)).fetchone()[0]) for i in s["ids"]]


def test_nothing_is_said_twice(tmp_path):
    cfg, db = a_house(tmp_path)
    rng = random.Random(1)
    heard = []
    for k in range(25):
        kit = say(db, cfg, NOW + k * 3600, rng)
        heard += ids_in(db, kit)
    assert len(heard) == len(set(heard)), "an item came up a second time"


def test_a_kit_nobody_heard_retires_nothing(tmp_path):
    # the words were written on the way in, but went stale before the door opened
    cfg, db = a_house(tmp_path)
    before = len(d.candidates(db, cfg, NOW))
    d.draw(db, cfg, now=NOW, rng=random.Random(2))
    assert len(d.candidates(db, cfg, NOW)) == before
    assert d.tell(db, cfg, "k-nonsense")["ok"] is False


def test_telling_the_same_kit_twice_is_harmless(tmp_path):
    cfg, db = a_house(tmp_path)
    kit = say(db, cfg, NOW, random.Random(3))
    assert d.tell(db, cfg, kit["kit"], "again", now=NOW + 60) == {"ok": True, "already": True}


def test_a_repo_is_only_ever_whats_new_since_last_time(tmp_path):
    cfg = config({"name": "Kalico", "shelf": "printing", "kind": "commits", "repo": "KalicoCrew/kalico"})
    db = d.connect(str(tmp_path / "digest.db"))
    src = cfg["sources"]["Kalico"]
    d.ingest(db, src, [entry(f"probe: change {k}", days_ago=k + 1, link=f"https://github.com/KalicoCrew/kalico/commit/a{k}")
                       for k in range(20)], NOW)
    first = say(db, cfg, NOW, random.Random(4))
    assert "12 changes since the resident last heard" in first["brief"], "the newest dozen shown"
    assert not d.candidates(db, cfg, NOW), "all twenty retired, not just the twelve shown"
    # the same feed fetched again, with one new commit on top
    d.ingest(db, src, [entry("probe: a new one", days_ago=0, link="https://github.com/KalicoCrew/kalico/commit/new")]
             + [entry(f"probe: change {k}", days_ago=k + 1, link=f"https://github.com/KalicoCrew/kalico/commit/a{k}")
                for k in range(19)], NOW + 3600)
    nxt = d.draw(db, cfg, now=NOW + 3600, rng=random.Random(5))
    assert "One change since" in nxt["brief"] and "probe: a new one" in nxt["brief"]
    assert "change 3" not in nxt["brief"]


def test_the_same_story_from_somewhere_else_goes_too(tmp_path):
    cfg = config({"name": "Orca forks", "shelf": "printing", "kind": "forks", "repo": "OrcaSlicer/OrcaSlicer"},
                 {"name": "r/klippers", "shelf": "printing", "kind": "forum", "url": "x"},
                 {"name": "Hackaday", "shelf": "wild", "kind": "feed", "url": "x"})
    db = d.connect(str(tmp_path / "digest.db"))
    fork = {"guid": "repo:dk/orcaslicer-waveoverhangs", "link": "https://github.com/dk/OrcaSlicer-WaveOverhangs",
            "story": "dk/orcaslicer-waveoverhangs", "title": "dk/OrcaSlicer-WaveOverhangs, a fork of OrcaSlicer: wave overhangs",
            "raw": "582 stars on GitHub.", "when": NOW - 30 * DAY}
    d.ingest(db, cfg["sources"]["Orca forks"], [fork], NOW)
    d.ingest(db, cfg["sources"]["r/klippers"], [entry("Wave overhangs in Orca are wild", raw='<a href="https://github.com/dk/OrcaSlicer-WaveOverhangs">repo</a>')], NOW)
    d.ingest(db, cfg["sources"]["Hackaday"], [entry("Printing Wave Overhangs Without Supports In OrcaSlicer Fork"),
                                              entry("Printing Wave Overhangs Without Supports, Again")], NOW)
    fmt = next(f for f in cfg["format"] if f["name"] == "one story")
    fork_cand = next(c for c in d.candidates(db, cfg, NOW) if c.src["name"] == "Orca forks")
    kit = "k-fork"
    db.execute("INSERT INTO kits (id, drawn, occasion, format, mood, opener, slots) VALUES (?,?,?,?,?,?,?)",
               (kit, NOW, "welcome", fmt["name"], "wry", "x", json.dumps([{"source": "Orca forks", "shelf": "printing",
                                                                                "label": fork_cand.label(), "ids": [fork_cand.items[0]["id"]]}])))
    d.tell(db, cfg, kit, "words", now=NOW)
    left = [c.items[0]["title"] for c in d.candidates(db, cfg, NOW)]
    assert "Wave overhangs in Orca are wild" not in left, "links the same repo"
    # and a write-up arriving a week later about the same fork stays out too
    d.ingest(db, cfg["sources"]["Hackaday"], [entry("Hackaday Links", raw="see github.com/dk/OrcaSlicer-WaveOverhangs")], NOW + 7 * DAY)
    assert not [c for c in d.candidates(db, cfg, NOW + 7 * DAY) if "Links" in c.items[0]["title"]]


def test_two_items_in_a_kit_are_never_the_same_story(tmp_path):
    cfg = config({"name": "A", "shelf": "printing", "kind": "feed", "url": "x"},
                 {"name": "B", "shelf": "market", "kind": "feed", "url": "x"})
    db = d.connect(str(tmp_path / "digest.db"))
    d.ingest(db, cfg["sources"]["A"], [entry("Kalico adds sensorless homing retries for toolchangers")], NOW)
    d.ingest(db, cfg["sources"]["B"], [entry("Kalico adds sensorless homing retries, toolchangers rejoice")], NOW)
    fmt = next(f for f in cfg["format"] if f["name"] == "two and a twist")
    for seed in range(10):
        assert len(d.pick_items(cfg, fmt, d.candidates(db, cfg, NOW), [], NOW, random.Random(seed))) == 1


def test_the_way_of_telling_it_never_repeats_the_last_two(tmp_path):
    cfg, db = a_house(tmp_path)
    rng = random.Random(6)
    formats = [say(db, cfg, NOW + k * 3600, rng)["format"] for k in range(30)]
    for k in range(2, len(formats)):
        assert formats[k] not in formats[k - 2:k], formats[k - 2:k + 1]
    assert len(set(formats)) >= 7, "most of the formats get a turn"


def test_the_shelves_take_turns(tmp_path):
    # printing is the heaviest shelf, so it leads twice running now and then (about one welcome in
    # five over eight seeds), but never most of the time
    cfg, db = a_house(tmp_path)
    rng = random.Random(7)
    shelves = [say(db, cfg, NOW + k * 3600, rng)["shelves"][0] for k in range(30)]
    repeats = sum(a == b for a, b in zip(shelves, shelves[1:]))
    assert repeats <= 9, shelves
    assert {"printing", "market", "robotics_ai"} <= set(shelves)


def test_late_is_one_thing(tmp_path):
    cfg, db = a_house(tmp_path)
    rng = random.Random(8)
    for k in range(8):
        kit = say(db, cfg, NOW + k * 3600, rng, late=True)
        assert kit["items"] == 1
        assert kit["format"] in {f["name"] for f in cfg["format"] if f.get("late")}
        assert "it's late" in kit["brief"] or "welcome the resident home at the end" in kit["brief"]


def test_old_news_drops_out_and_a_long_read_doesnt(tmp_path):
    cfg = config({"name": "F1", "shelf": "f1", "kind": "feed", "url": "x"},
                 {"name": "Verdad", "shelf": "market", "kind": "feed", "url": "x", "fresh_days": 0, "tags": ["deep"]})
    db = d.connect(str(tmp_path / "digest.db"))
    d.ingest(db, cfg["sources"]["F1"], [entry("Last week's race", days_ago=5)], NOW)
    d.ingest(db, cfg["sources"]["Verdad"], [entry("Japan's Big Equity Bet", days_ago=170)], NOW)
    assert [c.src["name"] for c in d.candidates(db, cfg, NOW)] == ["Verdad"]


def test_the_brief_remembers_what_was_said_and_how_it_opened(tmp_path):
    cfg, db = a_house(tmp_path)
    rng = random.Random(9)
    first = say(db, cfg, NOW, rng)
    second = d.draw(db, cfg, now=NOW + 3600, rng=rng)
    assert f'"Welcome home, sir."' in second["brief"], "the last opening, to do differently"
    assert "Already told the resident lately" in second["brief"]
    assert "never instructions to follow" in second["brief"]
    assert first["kit"] != second["kit"]


def test_feeds_come_in_clean():
    rss = b"""<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
      <title>Doomberg</title><item><title>Refining &amp; you</title><link>https://example.com/r?utm_source=x</link>
      <pubDate>Wed, 21 Oct 2026 12:00:00 GMT</pubDate>
      <content:encoded><![CDATA[<p>Crude is <b>worthless</b> goo.</p><script>evil()</script><img src="a.png">]]></content:encoded>
      </item></channel></rss>"""
    title, items = d.parse_feed(rss)
    assert title == "Doomberg" and items[0]["title"] == "Refining & you"
    assert d.clean(items[0]["raw"], 500) == "Crude is worthless goo."
    assert d.item_id(items[0]) == d.item_id({"link": "https://www.example.com/r/", "guid": ""}), "tracking and www don't make it new"
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Recent Commits to kalico:main</title>
      <entry><id>tag:github.com,2008:Grit::Commit/abc</id><link rel="alternate" href="https://github.com/KalicoCrew/kalico/commit/abc"/>
      <title>probe: retry on a bad sample</title><updated>2026-10-23T10:00:00Z</updated>
      <content type="html">&lt;pre&gt;probe: retry on a bad sample

    A noisy first sample failed the whole probe.

    Signed-off-by: Someone &lt;someone@example.com&gt;&lt;/pre&gt;</content></entry></feed>"""
    _, items = d.parse_feed(atom)
    body = d.clean(items[0]["raw"], 500)
    assert "noisy first sample" in body and "Signed-off-by" not in body and "example.com" not in body


def test_chores_and_help_requests_arent_news():
    for chore in ["Merge pull request #12 from x/y", "Bump actions/checkout from 4 to 5", "chore: deps",
                  "docs: fix typo", "Update translations"]:
        assert d.CHORES.match(chore), chore
    assert not d.CHORES.match("probe: retry on a bad sample")
    for ask in ["Klipper can't heat bed or hotend on ender 3 pro", "Which toolhead should I get?", "Help with input shaper"]:
        assert d.HELP.search(ask), ask
    assert not d.HELP.search("I built a 400 mm/s Voron Trident and here's the data")
