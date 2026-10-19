#!/usr/bin/env python3
"""The home dashboard, made from house.toml: ha/dashboards/home-hub.json, which tools/setup_ha.py
then saves into Home Assistant. Made rather than written by hand, because the rooms and the lights
in them are yours and the rest is the same in every house.

  python tools/dashboard.py        write ha/dashboards/home-hub.json

The pages: Home (the mode buttons, the at-a-glance row, one section per room with its lights), and
Routines and Hub always. TV, Printers and Appliances only when house.toml has one of those. The
fixed parts are in ha/dashboards/parts/ and use the standard names (docs/devices.md); edit those,
or this, never the generated file, which git ignores and the next deploy writes over. It's built
for the Hub's screen at a scale of 1.5 (1280 x 720 CSS pixels, three columns with the sidebar
hidden, host/40-kiosk.sh), and works on a phone too, a column at a time.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import house as housefile  # noqa: E402

PARTS = ROOT / "ha" / "dashboards" / "parts"
ICONS = (("living", "mdi:sofa"), ("kitchen", "mdi:stove"), ("bed", "mdi:bed"), ("bath", "mdi:shower"),
         ("office", "mdi:desk"), ("study", "mdi:desk"), ("hall", "mdi:door"), ("dining", "mdi:silverware-fork-knife"))
LIGHT_ICONS = {"ambient": "mdi:floor-lamp", "task": "mdi:ceiling-light", "accent": "mdi:led-strip-variant"}


def part(name):
    return json.loads((PARTS / f"{name}.json").read_text(encoding="utf-8"))


def tile(entity, name=None, columns=6, **kw):
    t = {"type": "tile", "entity": entity, "grid_options": {"columns": columns}, **kw}
    if name:
        t["name"] = name
    return t


def heading(text, icon):
    return {"type": "heading", "heading": text, "icon": icon, "heading_style": "title"}


def light_card(l):
    card = {"type": "custom:mushroom-light-card", "entity": l["becomes"],
            "icon": LIGHT_ICONS.get(l["layer"], "mdi:lightbulb"), "layout": "horizontal",
            "show_brightness_control": True, "use_light_color": True, "collapsible_controls": False,
            "tap_action": {"action": "toggle"}, "hold_action": {"action": "more-info"},
            "grid_options": {"columns": "full"}}
    if l["name"]:
        card["name"] = l["name"]
    return card


def tv_card():
    s = "{% set s = states('sensor.tv_status') %}"
    return {"type": "custom:mushroom-template-card", "entity": "media_player.tv",
            "icon": s + "{% if s in ['Off', 'Unreachable'] %}mdi:television-off{% elif s == 'Ambient mode' %}mdi:image-filter-hdr"
                        "{% elif s.endswith('playing') %}mdi:television-play{% elif s.endswith('paused') %}mdi:television-pause"
                        "{% else %}mdi:television{% endif %}",
            "color": s + "{% if s in ['Off', 'Unreachable'] %}grey{% elif s == 'Ambient mode' %}teal{% elif s.endswith('playing') %}green"
                         "{% elif s.endswith('paused') %}amber{% else %}blue{% endif %}",
            "primary": "TV",
            "secondary": s + "{% set t = state_attr('sensor.tv_status', 'title') %}{% if s in ['Off', 'Ambient mode', 'Home screen'] or not t %}"
                             "{{ s }}{% else %}{{ s }} · {{ t }}{% endif %}",
            "multiline_secondary": True, "tap_action": {"action": "navigate", "navigation_path": "/home-hub/tv"},
            "hold_action": {"action": "more-info"}, "grid_options": {"columns": 6}}


def jarvis_card():
    return {"type": "custom:mushroom-template-card", "entity": "input_boolean.jarvis_muted",
            "icon": "{{ 'mdi:microphone-off' if is_state('input_boolean.jarvis_muted', 'on') else 'mdi:microphone' }}",
            "color": "{{ 'red' if is_state('input_boolean.jarvis_muted', 'on') else 'green' }}",
            "primary": "Jarvis", "secondary": "{{ 'Muted' if is_state('input_boolean.jarvis_muted', 'on') else 'Listening' }}",
            "tap_action": {"action": "toggle"}, "grid_options": {"columns": 6}}


def room_sections(h):
    hub_room = h["hub"]["area"]
    out = []
    for room in h["rooms"]["names"]:
        icon = next((i for k, i in ICONS if k in room.lower()), "mdi:home-outline")
        cards = [heading(room, icon)]
        cards += [light_card(l) for l in h["light"] if l["area"].lower() == room.lower()]
        if h["fire_tv"]["address"] and h["fire_tv"]["area"].lower() == room.lower():
            cards.append(tv_card())
        if room.lower() == hub_room.lower():
            cards.append(jarvis_card())
            cards.append(tile("light.hub_500_screen", "Hub screen"))
        if len(cards) > 1:
            out.append({"type": "grid", "cards": cards})
    return out


def printers_view(h):
    sections = []
    if h["devices"]["klipper"] or h["klipper"]["moonraker"]:
        sections.append({"type": "grid", "cards": [
            heading("Klipper printer", "mdi:printer-3d"),
            {"type": "markdown", "content": "{{ states('sensor.klipper_summary') }}", "grid_options": {"columns": "full"}},
            tile("sensor.klipper_progress", "Progress"), tile("sensor.klipper_time_left", "Left"),
            tile("sensor.klipper_extruder_temperature", "Nozzle"), tile("sensor.klipper_nozzle_target", "Nozzle target"),
            tile("sensor.klipper_bed_temperature", "Bed"), tile("sensor.klipper_bed_target", "Bed target"),
            tile("sensor.klipper_layer", "Layer"), tile("sensor.klipper_meter", "Power"),
            tile("light.klipper_case_light", "Case light"), tile("sensor.klipper_heater_duty", "Heaters"),
            tile("button.klipper_pause_print", "Pause", 4), tile("button.klipper_resume_print", "Resume", 4),
            tile("button.klipper_cancel_print", "Cancel", 4)]})
    if h["devices"]["bambu"] or "bambu" in h["extras"]["install"]:
        sections.append({"type": "grid", "cards": [
            heading("Bambu printer", "mdi:printer-3d"),
            {"type": "markdown", "content": "{{ states('sensor.bambu_summary') }}", "grid_options": {"columns": "full"}},
            tile("sensor.bambu_print_progress", "Progress"), tile("sensor.bambu_time_left", "Left"),
            tile("sensor.bambu_nozzle_temperature", "Nozzle"), tile("sensor.bambu_bed_temperature", "Bed"),
            tile("sensor.bambu_chamber_temperature", "Chamber"), tile("sensor.bambu_layer", "Layer"),
            tile("light.bambu_chamber_light", "Chamber light"), tile("sensor.bambu_meter", "Power"),
            tile("sensor.bambu_ams_1_humidity", "AMS humidity"), tile("binary_sensor.bambu_hms_errors", "Health")]})
    if not sections:
        return None
    sections.append({"type": "grid", "cards": [
        heading("Both", "mdi:printer-3d-nozzle"), tile("sensor.printers_meter", "Power, together"),
        tile("input_boolean.auto_printers", "Printer alerts")]})
    return {"title": "Printers", "path": "printers", "icon": "mdi:printer-3d", "type": "sections",
            "max_columns": 3, "sections": sections}


def appliances_view(h):
    sections = []
    if h["devices"]["vacuum"]:
        sections.append({"type": "grid", "cards": [
            heading("Vacuum", "mdi:robot-vacuum"),
            {"type": "custom:mushroom-vacuum-card", "entity": "vacuum.robot_vacuum", "name": "Robot vacuum",
             "commands": ["start_pause", "stop", "locate", "return_home"], "grid_options": {"columns": "full"}},
            tile("sensor.robot_vacuum_battery", "Battery"), tile("sensor.robot_vacuum_current_room", "Room"),
            tile("script.vacuum_clean", "Clean what it can reach"), tile("timer.vacuum_later", "Later"),
            tile("input_boolean.auto_vacuum", "Vacuum on its own"), tile("input_select.vacuum_when_leaving", "When I leave"),
            tile("input_boolean.vacuum_docks_on_arrival", "Docks when I arrive")]})
    if h["devices"]["washer"]:
        sections.append({"type": "grid", "cards": [
            heading("Washer", "mdi:washing-machine"),
            tile("binary_sensor.washer_running", "Running"), tile("sensor.washer_current_status", "Status"),
            tile("sensor.washer_remaining_time", "Done at"), tile("input_datetime.washer_done_at", "Last load"),
            tile("input_boolean.auto_laundry", "Laundry reminders")]})
    if h["devices"]["doorbell"] or h["resident"]["face"]:
        sections.append({"type": "grid", "cards": [
            heading("Doorbell", "mdi:doorbell"),
            {"type": "picture", "image": "/local/doorbell_last.jpg", "grid_options": {"columns": "full"}},
            tile("input_datetime.doorbell_last_ring", "Last ring"), tile("sensor.doorbell_battery", "Battery"),
            tile("input_boolean.auto_doorbell", "Announcements")]})
    if not sections:
        return None
    return {"title": "Appliances", "path": "appliances", "icon": "mdi:washing-machine", "type": "sections",
            "max_columns": 3, "sections": sections}


def build(h):
    home = {"title": "Home", "path": "home", "icon": "mdi:home", "type": "sections", "max_columns": 3,
            "sections": [part("chips"), *room_sections(h), part("glance")]}
    views = [home, part("routines")]
    if h["fire_tv"]["address"]:
        views.append(part("tv"))
    for v in (printers_view(h), appliances_view(h)):
        if v:
            views.append(v)
    views.append(part("hub"))
    return {"title": "Home", "views": views}


def main():
    out = ROOT / "ha" / "dashboards" / "home-hub.json"
    out.write_text(json.dumps(build(housefile.load()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
