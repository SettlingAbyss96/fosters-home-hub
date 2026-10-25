#!/usr/bin/env python3
"""hub-journal: Jarvis asks how it went, once you're home, and keeps what you say.

Home Assistant sends every new phone position here (packages/journal.yaml). From those this works
out the stays, somewhere that isn't home for a while, and what kind of place each one was, from a
copy of OpenStreetMap's cafes, restaurants, shops and the rest in a box around home. When you get
in, Home Assistant asks for a question about the trip (GET /ask), Jarvis asks it after the
welcome home and listens, and the answer comes back (POST /answer) to be kept here, with a copy in
Home Assistant's /config/journal so it rides along with the backups.

What gets asked about, out of journal.toml (journal.example.toml until you make your own):
  - work, once a day, however ordinary the day
  - anywhere new that's a cafe, a restaurant, a bar, a shop, a gym, a park, a museum or the like
  - somewhere familiar only after a while (again_days), so the usual coffee doesn't get the same
    question every morning. A supermarket gets asked about the first time and never again
  - never a doctor's, a pharmacy, a place of worship, a petrol station, a bank or anywhere with
    no name on the map, which is mostly other people's houses
Two places at most in one question, work first, then anywhere new, then the longest stay. The
question is a template from journal.toml, never one of the last three used for that kind.

Positions never leave the house. The map comes down once a month as a box around home, nothing
about where you've been goes anywhere, and the questions are written here, not by a model.

  GET  /ask             the question for the trip just ending, or {} when there's nothing to ask
  POST /answer          {"ask": id, "answer": text, "heard": true}: "" is asked and not answered
  POST /point           {"t", "lat", "lon", "acc", "zone", "aoi"}
  POST /note            {"text"}: a line for the journal with no place
  GET  /journal?days=7  the entries, newest first
  GET  /today           today's entries as one spoken paragraph
  GET  /status

  hub_journal.py                  the service, on 10231 (fenced to the VM, host/59-journal.sh)
  hub_journal.py --import CSV     a location log you already keep (time, zone, latitude, longitude,
                                  accuracy), as history
  hub_journal.py --map            fetch the map now
  hub_journal.py --stays [DAYS]   the stays it sees, and what it would ask now, without keeping it
"""
import argparse
import csv
import json
import math
import os
import random
import sqlite3
import statistics
import threading
import time
import tomllib
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "hub-journal/1.0 (a home's map of the neighbourhood, once a month)"
DAY = 86400.0
LOCK = threading.Lock()
# where a stay is, unless journal.toml's [stays] says otherwise: shorter than min_minutes is a stop,
# not a stay; within near_home_m of home is home, because the GPS wanders; points within radius_m
# of each other are one place; the phone moves at about travel_mps between places, which says when
# a stay with one position in it ended; back at the same place within merge_minutes is one stay;
# a position worse than max_acc_m is no position at all
STAYS = {"min_minutes": 8, "near_home_m": 350, "radius_m": 120, "travel_mps": 10, "merge_minutes": 30, "max_acc_m": 150}
# the map: a box around home at least radius_km out, grown to cover where the phone goes, up to max_km
MAP = {"radius_km": 20, "max_km": 40, "refresh_days": 30, "url": "https://overpass-api.de/api/interpreter"}
# Which place on the map a stay was at is a guess, so it's made as one (docs/journal.md): each place
# within reach gets a likelihood from how far it is, against how blurred the position was and how
# big the place is (a shop's node sits on its door, a building's centre can be half a supermarket
# away), and "somewhere not on the map" gets a share of its own. The best one has to be more likely
# than not, or the stay goes down as somewhere with no name (or the area of interest it's in), which
# never gets a question. Sizes are the spread of a node and a building in metres, REACH how far to
# look, UNMAPPED how much weight the unmapped gets
SIZE_NODE, SIZE_WAY = 10, 35
REACH = 110
UNMAPPED = 1.0
SURE = 0.5
# a visit that ended longer ago than this isn't part of the trip you're just back from
WINDOW_HOURS = 12

# OpenStreetMap's tags to the kinds of place journal.toml has questions for. Anything not here is
# "other" and never asked about, and so are errands, health, worship, school, lodging and personal
# care, which are on the map so a stay at the pharmacy isn't put down to the cafe next door
KINDS = {
    "amenity": {"cafe": "cafe", "restaurant": "restaurant", "fast_food": "restaurant", "food_court": "restaurant",
                "ice_cream": "restaurant", "bbq": "restaurant", "bar": "bar", "pub": "bar", "biergarten": "bar",
                "nightclub": "bar", "cinema": "culture", "theatre": "culture", "arts_centre": "culture",
                "library": "culture", "concert_hall": "culture", "events_venue": "culture", "marketplace": "shop",
                "fuel": "errand", "parking": "errand", "parking_entrance": "errand", "car_wash": "errand",
                "charging_station": "errand", "bank": "errand", "atm": "errand", "post_office": "errand",
                "fire_station": "errand", "police": "errand", "townhall": "errand", "courthouse": "errand",
                "clinic": "health", "dentist": "health", "doctors": "health", "hospital": "health",
                "pharmacy": "health", "veterinary": "health", "place_of_worship": "worship",
                "school": "school", "kindergarten": "school", "university": "school", "college": "school"},
    "shop": {"coffee": "cafe", "supermarket": "grocery", "convenience": "grocery", "greengrocer": "grocery",
             "butcher": "grocery", "hairdresser": "personal", "beauty": "personal", "massage": "personal",
             "tattoo": "personal", "chemist": "health", "optician": "health", "medical_supply": "health",
             "car_repair": "errand", "tyres": "errand", "dry_cleaning": "errand", "laundry": "errand"},
    "leisure": {"fitness_centre": "gym", "sports_centre": "gym", "climbing": "gym", "swimming_pool": "gym",
                "ice_rink": "gym", "park": "outdoors", "garden": "outdoors", "nature_reserve": "outdoors",
                "stadium": "culture", "bowling_alley": "culture", "golf_course": "outdoors"},
    "tourism": {"museum": "culture", "gallery": "culture", "zoo": "culture", "aquarium": "culture",
                "theme_park": "culture", "attraction": "culture", "viewpoint": "outdoors", "hotel": "lodging"},
    "craft": {"brewery": "bar", "winery": "bar", "distillery": "bar"},
}
# a shop of any other sort is a shop
ANY_SHOP = "shop"
TAGS = ["amenity", "shop", "leisure", "tourism", "craft"]


def log(*a):
    print(*a, flush=True)


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg["stays"] = {**STAYS, **cfg.get("stays", {})}
    cfg["map"] = {**MAP, **cfg.get("map", {})}
    cfg.setdefault("work_zone", "Work")
    cfg.setdefault("kinds", {})
    return cfg


def connect(path):
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS points (t REAL PRIMARY KEY, lat REAL, lon REAL, acc REAL, zone TEXT, aoi TEXT);
        CREATE TABLE IF NOT EXISTS pois (osm TEXT PRIMARY KEY, lat REAL, lon REAL, name TEXT, kind TEXT, tag TEXT);
        CREATE INDEX IF NOT EXISTS pois_lat ON pois (lat);
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY, lat REAL, lon REAL, name TEXT, kind TEXT, osm TEXT UNIQUE, zone TEXT UNIQUE,
            area TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY, place INTEGER, start REAL, end REAL, asked REAL, passed INTEGER DEFAULT 0,
            UNIQUE (place, start));
        CREATE TABLE IF NOT EXISTS asks (
            id INTEGER PRIMARY KEY, at REAL, visits TEXT, kinds TEXT, templates TEXT, question TEXT, heard REAL);
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY, at REAL, ask INTEGER, places TEXT, question TEXT, answer TEXT);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return db


def meta(db, key, value=None):
    if value is None:
        r = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
    db.commit()


def dist(a_lat, a_lon, b_lat, b_lon):
    """Metres between two points, on a round Earth"""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


# -- positions --------------------------------------------------------------------------------
def add_point(db, p):
    aoi = p.get("aoi")
    if isinstance(aoi, list):
        aoi = aoi[0] if aoi else None
    aoi = None if not aoi or str(aoi).strip() in ("N/A", "unknown", "None") else str(aoi).strip()[:80]
    db.execute("INSERT OR REPLACE INTO points VALUES (?, ?, ?, ?, ?, ?)",
               (float(p["t"]), float(p["lat"]), float(p["lon"]), float(p.get("acc") or 0),
                str(p.get("zone") or "not_home"), aoi))
    db.commit()


def import_csv(db, path):
    """The location log Home Assistant keeps (time, zone, latitude, longitude, accuracy, ...)"""
    n = 0
    with open(path, encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r) < 5 or not r[0][:4].isdigit():
                continue
            try:
                t = datetime.fromisoformat(r[0]).timestamp()
                db.execute("INSERT OR IGNORE INTO points VALUES (?, ?, ?, ?, ?, NULL)",
                           (t, float(r[2]), float(r[3]), float(r[4] or 0), r[1] or "not_home"))
                n += 1
            except ValueError:
                continue
    db.commit()
    return n


def home_of(db):
    """Home is where the phone says home, the median of its last few hundred positions there"""
    rows = db.execute("SELECT lat, lon FROM points WHERE zone = 'home' ORDER BY t DESC LIMIT 400").fetchall()
    if len(rows) < 5:
        return None
    return statistics.median(r["lat"] for r in rows), statistics.median(r["lon"] for r in rows)


def stays(points, cfg, home):
    """Somewhere that isn't home for a while, from the positions in time order. iOS reports a new
    position when the phone has moved a few hundred metres, so a stay is often one position and then
    nothing until the next place, and it ended about as long before that as the trip there took"""
    s = cfg["stays"]
    pts = [p for p in points if (p["acc"] or 0) <= s["max_acc_m"]]
    out, i = [], 0
    while i < len(pts):
        p = pts[i]
        if p["zone"] == "home":
            i += 1
            continue
        named = p["zone"] not in ("not_home", "", None)
        j, lat, lon = i, p["lat"], p["lon"]
        while j + 1 < len(pts):
            q = pts[j + 1]
            if named and q["zone"] != p["zone"]:
                break
            if not named and (q["zone"] != "not_home" or dist(lat, lon, q["lat"], q["lon"]) > s["radius_m"]):
                break
            j += 1
            lat = statistics.fmean(x["lat"] for x in pts[i: j + 1])
            lon = statistics.fmean(x["lon"] for x in pts[i: j + 1])
        if j + 1 >= len(pts):                     # still there: not a stay until it's over
            break
        last, nxt = pts[j], pts[j + 1]
        end = max(last["t"], nxt["t"] - dist(last["lat"], last["lon"], nxt["lat"], nxt["lon"]) / s["travel_mps"])
        near_home = home is not None and not named and dist(lat, lon, *home) < s["near_home_m"]
        if end - p["t"] >= s["min_minutes"] * 60 and not near_home:
            aois = Counter(x["aoi"] for x in pts[i: j + 1] if x["aoi"])
            out.append({"start": p["t"], "end": end, "lat": lat, "lon": lon,
                        "acc": statistics.median(x["acc"] or 0 for x in pts[i: j + 1]),
                        "zone": p["zone"] if named else None, "aoi": aois.most_common(1)[0][0] if aois else None})
        i = j + 1
    return out


# -- the map ----------------------------------------------------------------------------------
def kind_of(tags):
    for t in TAGS:
        v = tags.get(t)
        if not v:
            continue
        k = KINDS[t].get(v)
        if k:
            return k, f"{t}={v}"
        if t == "shop":
            return ANY_SHOP, f"shop={v}"
    return "other", ""


def map_box(db, cfg):
    """(south, west, north, east) around home, big enough for where the phone has been"""
    home = home_of(db)
    if home is None:
        return None
    far = sorted(dist(r["lat"], r["lon"], *home) for r in
                 db.execute("SELECT lat, lon FROM points WHERE zone != 'home' ORDER BY t DESC LIMIT 5000"))
    p95 = far[int(len(far) * 0.95)] / 1000 if far else 0
    r = min(cfg["map"]["max_km"], max(cfg["map"]["radius_km"], p95 + 2)) * 1000
    dlat = r / 111320
    dlon = r / (111320 * math.cos(math.radians(home[0])))
    return round(home[0] - dlat, 3), round(home[1] - dlon, 3), round(home[0] + dlat, 3), round(home[1] + dlon, 3)


def overpass_query(box):
    b = ",".join(str(x) for x in box)
    return (f"[out:csv(::type,::id,::lat,::lon,name,{','.join(TAGS)};false;\"\\t\")][timeout:180][bbox:{b}];"
            "(nwr[amenity][name];nwr[shop][name];"
            "nwr[leisure~\"^(fitness_centre|sports_centre|park|stadium|bowling_alley|climbing|golf_course|ice_rink|"
            "swimming_pool|garden|nature_reserve)$\"][name];"
            "nwr[tourism~\"^(museum|gallery|attraction|zoo|aquarium|theme_park|hotel|viewpoint)$\"][name];"
            "nwr[craft~\"^(brewery|winery|distillery)$\"][name];);out center qt;")


def parse_pois(text):
    out = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 5 or not f[2] or not f[4]:
            continue
        tags = dict(zip(TAGS, f[5:5 + len(TAGS)]))
        kind, tag = kind_of(tags)
        try:
            out.append((f[0][0] + f[1], float(f[2]), float(f[3]), f[4].strip()[:80], kind, tag))
        except (ValueError, IndexError):
            continue
    return out


def fetch_map(db, cfg, now=None):
    now = time.time() if now is None else now
    box = map_box(db, cfg)
    if box is None:
        return 0
    data = urllib.parse.urlencode({"data": overpass_query(box)}).encode()
    req = urllib.request.Request(cfg["map"]["url"], data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=240) as r:
        pois = parse_pois(r.read().decode("utf-8", "replace"))
    if len(pois) < 50:                            # an error page or a bad day: keep the old map
        raise RuntimeError(f"only {len(pois)} places came back")
    with LOCK:
        db.execute("DELETE FROM pois")
        db.executemany("INSERT OR REPLACE INTO pois VALUES (?, ?, ?, ?, ?, ?)", pois)
        db.commit()
        meta(db, "map_at", now)
        meta(db, "map_box", json.dumps(box))
        rematch(db)
    return len(pois)


def map_due(db, cfg, now):
    at = float(meta(db, "map_at") or 0)
    return now - at > cfg["map"]["refresh_days"] * DAY


def near_pois(db, lat, lon, acc):
    """[(probability, distance, poi)] for the places on the map this stay could have been at, best
    first. A place at distance d with spread sigma (the position's accuracy and the place's size
    together) has likelihood exp(-d^2 / 2 sigma^2) / (2 pi sigma^2), a round Gaussian in metres, and
    the unmapped has UNMAPPED / (pi REACH^2), as if it were anywhere in reach"""
    dlat = REACH / 111320
    dlon = REACH / (111320 * max(0.2, math.cos(math.radians(lat))))
    found = []
    for r in db.execute("SELECT * FROM pois WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                        (lat - dlat, lat + dlat, lon - dlon, lon + dlon)):
        d = dist(lat, lon, r["lat"], r["lon"])
        if d > REACH:
            continue
        size = SIZE_NODE if r["osm"].startswith("n") else SIZE_WAY
        var = max(acc, 5) ** 2 + size ** 2
        found.append((math.exp(-d * d / (2 * var)) / (2 * math.pi * var), d, dict(r)))
    total = sum(f[0] for f in found) + UNMAPPED / (math.pi * REACH ** 2)
    return sorted(((f[0] / total, f[1], f[2]) for f in found), key=lambda x: -x[0])


def place_for(db, cfg, s):
    """The place a stay was at: its zone, the place on the map it most likely was, the area of
    interest it's in, or somewhere with no name"""
    if s["zone"]:
        kind = "work" if s["zone"].lower() == cfg["work_zone"].lower() else "zone"
        return upsert_place(db, "zone", s["zone"], s["lat"], s["lon"], s["zone"], kind)
    near = near_pois(db, s["lat"], s["lon"], s["acc"])
    if near and near[0][0] >= SURE:
        p = near[0][2]
        return upsert_place(db, "osm", p["osm"], p["lat"], p["lon"], p["name"], p["kind"])
    if s["aoi"]:
        return upsert_place(db, "area", s["aoi"], s["lat"], s["lon"], s["aoi"], "area")
    for r in db.execute("SELECT * FROM places WHERE osm IS NULL AND zone IS NULL AND area IS NULL"):
        if dist(s["lat"], s["lon"], r["lat"], r["lon"]) <= cfg["stays"]["radius_m"]:
            return r["id"]
    db.execute("INSERT INTO places (lat, lon, name, kind) VALUES (?, ?, NULL, NULL)", (s["lat"], s["lon"]))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def upsert_place(db, col, key, lat, lon, name, kind):
    r = db.execute(f"SELECT id FROM places WHERE {col} = ?", (key,)).fetchone()
    if r:
        return r["id"]
    db.execute(f"INSERT INTO places (lat, lon, name, kind, {col}) VALUES (?, ?, ?, ?, ?)", (lat, lon, name, kind, key))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def rematch(db):
    """Places found before the map came down get their names now"""
    for r in db.execute("SELECT * FROM places WHERE osm IS NULL AND zone IS NULL AND area IS NULL").fetchall():
        near = near_pois(db, r["lat"], r["lon"], 25)
        if near and near[0][0] >= SURE:
            p = near[0][2]
            if db.execute("SELECT 1 FROM places WHERE osm = ?", (p["osm"],)).fetchone():
                continue
            db.execute("UPDATE places SET name = ?, kind = ?, osm = ? WHERE id = ?", (p["name"], p["kind"], p["osm"], r["id"]))
    db.commit()


# -- visits -----------------------------------------------------------------------------------
def refresh_visits(db, cfg, now, hours=48, history=False):
    """Stays since `hours` ago (everything, for history) become visits to places. A stay that's
    back at the same place within merge_minutes of the last one is the same visit"""
    since = 0 if history else now - hours * 3600
    points = [dict(r) for r in db.execute("SELECT * FROM points WHERE t >= ? ORDER BY t", (since,))]
    home = home_of(db)
    merged = []
    for s in stays(points, cfg, home):
        s["place"] = place_for(db, cfg, s)
        if merged and merged[-1]["place"] == s["place"] and s["start"] - merged[-1]["end"] < cfg["stays"]["merge_minutes"] * 60:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(s)
    for s in merged:
        db.execute("INSERT INTO visits (place, start, end, asked) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT (place, start) DO UPDATE SET end = excluded.end",
                   (s["place"], s["start"], s["end"], s["end"] if history else None))
    db.commit()
    return merged


def kind_cfg(cfg, kind):
    return cfg["kinds"].get(kind or "")


def worth_asking(db, cfg, v, now):
    """(score, first) for a visit worth a question, or None: work once a day, anywhere new, and
    somewhere familiar again only after its kind's again_days"""
    k = kind_cfg(cfg, v["kind"])
    if not k or not v["name"]:
        return None
    minutes = (v["end"] - v["start"]) / 60
    if minutes < k.get("min_minutes", 15):
        return None
    before = db.execute("SELECT COUNT(*) FROM visits WHERE place = ? AND start < ?", (v["place"], v["start"])).fetchone()[0]
    last = db.execute("SELECT MAX(asked) FROM visits WHERE place = ? AND asked IS NOT NULL AND passed = 0 AND id != ?",
                      (v["place"], v["id"])).fetchone()[0]
    if v["kind"] == "work":
        today = datetime.fromtimestamp(now).date()
        if last and datetime.fromtimestamp(last).date() == today:
            return None
        return 100 + math.log1p(minutes), before == 0
    if before and "again_days" not in k:
        return None                               # this kind only the first time
    if before and last and now - last < k["again_days"] * DAY:
        return None
    return (10 if not before else 0) + k.get("weight", 1.0) + math.log1p(minutes) / 4, before == 0


def pick_template(db, kind, which, options, rng):
    """One of the options, never one of the last three used for this kind and form"""
    recent = []
    for r in db.execute("SELECT templates FROM asks WHERE heard IS NOT NULL ORDER BY at DESC LIMIT 12"):
        recent += [t for t in json.loads(r["templates"]) if t.startswith(f"{kind}.{which}.")]
    used = recent[:3]
    pool = [i for i in range(len(options)) if f"{kind}.{which}.{i}" not in used] or list(range(len(options)))
    i = rng.choice(pool)
    return f"{kind}.{which}.{i}", options[i]


def ask(db, cfg, now=None, rng=None, keep=True):
    """The question for the trip just ending: {"ask", "question", "places"}, or {} for nothing"""
    now = time.time() if now is None else now
    rng = rng or random.SystemRandom()
    with LOCK:
        refresh_visits(db, cfg, now)
        rows = db.execute("SELECT v.*, p.name, p.kind FROM visits v JOIN places p ON p.id = v.place "
                          "WHERE v.asked IS NULL AND v.end > ? ORDER BY v.start", (now - WINDOW_HOURS * 3600,)).fetchall()
        scored = []
        for v in rows:
            w = worth_asking(db, cfg, dict(v), now)
            if w:
                scored.append((w[0], w[1], dict(v)))
        if not scored:
            return {}
        scored.sort(key=lambda x: -x[0])
        chosen = sorted(scored[:2], key=lambda x: x[2]["start"])
        chosen.sort(key=lambda x: 0 if x[2]["kind"] == "work" else 1)
        parts, templates = [], []
        for n, (_, first, v) in enumerate(chosen):
            k = kind_cfg(cfg, v["kind"])
            if n == 0:
                which = "first" if first and k.get("first") else "again" if k.get("again") else "first"
            else:
                which = "also"
            options = k.get(which) or k.get("first") or k.get("again")
            key, text = pick_template(db, v["kind"], which, options, rng)
            parts.append(text.format(name=v["name"]))
            templates.append(key)
        question = " ".join(parts)
        places = [{"name": v["name"], "kind": v["kind"], "first": first,
                   "minutes": round((v["end"] - v["start"]) / 60)} for _, first, v in chosen]
        if not keep:
            return {"ask": None, "question": question, "places": places}
        db.execute("INSERT INTO asks (at, visits, kinds, templates, question) VALUES (?, ?, ?, ?, ?)",
                   (now, json.dumps([v["id"] for _, _, v in chosen]), json.dumps([v["kind"] for _, _, v in chosen]),
                    json.dumps(templates), question))
        db.commit()
        return {"ask": db.execute("SELECT last_insert_rowid()").fetchone()[0], "question": question, "places": places}


def answer(db, cfg, ask_id, text, heard=True, now=None):
    """What was said. Heard and answered is an entry; heard and not answered is asked all the
    same, so it doesn't come round again; not heard at all leaves it for next time. Either way the
    rest of the trip's visits are left out from now on, so last night's shop doesn't turn up
    tomorrow"""
    now = time.time() if now is None else now
    text = (text or "").strip()[:2000]
    with LOCK:
        a = db.execute("SELECT * FROM asks WHERE id = ?", (ask_id,)).fetchone()
        if a is None:
            return {"error": "no such ask"}
        if not heard:
            return {"kept": False}
        ids = json.loads(a["visits"])
        db.execute("UPDATE asks SET heard = ? WHERE id = ?", (now, ask_id))
        db.execute(f"UPDATE visits SET asked = ? WHERE id IN ({','.join('?' * len(ids))})", (now, *ids))
        db.execute("UPDATE visits SET asked = ?, passed = 1 WHERE asked IS NULL AND end <= ?", (now, a["at"]))
        names = [r["name"] for r in db.execute(
            f"SELECT p.name FROM visits v JOIN places p ON p.id = v.place WHERE v.id IN ({','.join('?' * len(ids))}) "
            "ORDER BY v.start", ids)]
        if text:
            db.execute("INSERT INTO entries (at, ask, places, question, answer) VALUES (?, ?, ?, ?, ?)",
                       (now, ask_id, ", ".join(names), a["question"], text))
        db.commit()
        return {"kept": bool(text), "places": names}


def note(db, text, now=None):
    now = time.time() if now is None else now
    text = (text or "").strip()[:2000]
    if not text:
        return {"kept": False}
    with LOCK:
        db.execute("INSERT INTO entries (at, ask, places, question, answer) VALUES (?, NULL, '', '', ?)", (now, text))
        db.commit()
    return {"kept": True}


def journal(db, days=7, now=None):
    now = time.time() if now is None else now
    return [{"at": r["at"], "day": f"{datetime.fromtimestamp(r['at']):%a %b} {datetime.fromtimestamp(r['at']).day}",
             "time": datetime.fromtimestamp(r["at"]).strftime("%I:%M %p").lstrip("0"), "places": r["places"],
             "question": r["question"], "answer": r["answer"]}
            for r in db.execute("SELECT * FROM entries WHERE at > ? ORDER BY at DESC", (now - days * DAY,))]


def today(db, now=None):
    """Today's entries as one paragraph, for "read me today's journal\""""
    now = time.time() if now is None else now
    start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = db.execute("SELECT * FROM entries WHERE at >= ? ORDER BY at", (start,)).fetchall()
    said = [(f"About {r['places']}: " if r["places"] else "A note: ") + r["answer"].rstrip(".") + "." for r in rows]
    return {"n": len(rows), "text": " ".join(said)}


def status(db, cfg, now=None):
    now = time.time() if now is None else now
    week = db.execute("SELECT p.kind, COUNT(*) n FROM visits v JOIN places p ON p.id = v.place WHERE v.start > ? "
                      "GROUP BY p.kind", (now - 7 * DAY,)).fetchall()
    return {"points": db.execute("SELECT COUNT(*) FROM points").fetchone()[0],
            "places": db.execute("SELECT COUNT(*) FROM places").fetchone()[0],
            "map": db.execute("SELECT COUNT(*) FROM pois").fetchone()[0],
            "map_age_days": round((now - float(meta(db, "map_at") or 0)) / DAY, 1) if meta(db, "map_at") else None,
            "visits_this_week": {r["kind"] or "unnamed": r["n"] for r in week},
            "entries": db.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "home_known": home_of(db) is not None}


# -- the service ------------------------------------------------------------------------------
def serve(cfg, db_path, port):
    def mapper():
        db = connect(db_path)
        while True:
            try:
                if map_due(db, cfg, time.time()) and home_of(db):
                    log("map:", fetch_map(db, cfg), "places")
            except Exception as e:  # noqa: BLE001
                log("map fetch failed:", e)
                meta(db, "map_at", time.time() - (cfg["map"]["refresh_days"] - 1) * DAY)   # again tomorrow
            time.sleep(3600)

    threading.Thread(target=mapper, daemon=True).start()

    class Api(BaseHTTPRequestHandler):
        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            db = connect(db_path)
            try:
                if u.path == "/ask":
                    self.reply(200, ask(db, cfg))
                elif u.path == "/journal":
                    self.reply(200, {"entries": journal(db, float(q.get("days", 7)))})
                elif u.path == "/today":
                    self.reply(200, today(db))
                elif u.path == "/status":
                    self.reply(200, status(db, cfg))
                else:
                    self.reply(404, {"error": "no such thing"})
            finally:
                db.close()

        def do_POST(self):  # noqa: N802
            if self.path not in ("/point", "/answer", "/note"):
                return self.reply(404, {"error": "no such thing"})
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 100_000)) or b"{}")
            except ValueError:
                return self.reply(400, {"error": "not JSON"})
            db = connect(db_path)
            try:
                if self.path == "/point":
                    with LOCK:
                        add_point(db, body)
                    self.reply(200, {"ok": True})
                elif self.path == "/answer":
                    heard = body.get("heard", True) not in (False, "false", "False", 0, "0")
                    self.reply(200, answer(db, cfg, int(body.get("ask") or 0), str(body.get("answer") or ""), heard))
                else:
                    self.reply(200, note(db, str(body.get("text") or "")))
            except (KeyError, ValueError, TypeError) as e:
                self.reply(400, {"error": str(e)[:200]})
            finally:
                db.close()

        def log_message(self, fmt, *args):
            pass

    log(f"hub-journal on {port}")
    ThreadingHTTPServer(("0.0.0.0", port), Api).serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=os.path.join(HERE, "journal.toml") if os.path.exists(os.path.join(HERE, "journal.toml"))
                   else os.path.join(HERE, "journal.example.toml"))
    p.add_argument("--db", default=os.environ.get("JOURNAL_DB", "/var/lib/hub-journal/journal.db"))
    p.add_argument("--port", type=int, default=10231)
    p.add_argument("--import", dest="csv", help="the location log, as history: nothing in it gets asked about")
    p.add_argument("--map", action="store_true", help="fetch the map now")
    p.add_argument("--stays", type=float, nargs="?", const=7, help="print the stays of the last DAYS and what it would ask")
    a = p.parse_args()
    cfg = load_config(a.config)
    if a.csv or a.map or a.stays is not None:
        db = connect(a.db)
        if a.csv:
            log("points:", import_csv(db, a.csv))
        if a.map or (a.csv and not db.execute("SELECT 1 FROM pois LIMIT 1").fetchone()):
            log("map:", fetch_map(db, cfg), "places")
        if a.csv:
            log("visits:", len(refresh_visits(db, cfg, time.time(), history=True)))
        if a.stays is not None:
            for r in db.execute("SELECT v.*, p.name, p.kind FROM visits v JOIN places p ON p.id = v.place "
                                "WHERE v.start > ? ORDER BY v.start", (time.time() - a.stays * DAY,)):
                log(f"{datetime.fromtimestamp(r['start']):%a %m-%d %H:%M}  {(r['end'] - r['start']) / 60:4.0f} min  "
                    f"{r['kind'] or '-':10} {r['name'] or '(no name)'}")
            log(json.dumps(ask(db, cfg, keep=False)))
        return
    serve(cfg, a.db, a.port)


if __name__ == "__main__":
    main()
