"""The light curve: how bright and how warm the ambient layer should be right now. One function of
the day instead of a number per mode, so the light moves with the daylight and with the bedtime
rather than in steps when the mode changes. docs/lighting.md has where each part comes from.

    daylight D, 0 to 1: the sun's height, counted as full from 35 degrees up, times Kasten and
      Czeplak's cloud factor 1 - 0.75 c^3.4 (c the cloud cover, 0 to 1). With decent windows,
      daylight is most of the light by day, so the lamps can sit lower
    wind-down w, 0 to 1: nothing until an hour before (bedtime - H), all of it from there until the
      planned wake time, a smoothstep in between. H is input_number.wind_down_hours, 3 to start: the
      2022 consensus (Brown et al.) puts evening light at its lowest from three hours before bed
    level  = dark - (dark - daylight) * D, then toward the wind-down level by w
    kelvin = 4000 K in the morning, easing to 2700 K between 1 and 3 PM (and by w, if the wind-down
      starts earlier), never below the floor: under 2700 K a lot of colour lamps get much dimmer
      (probably mixing the warmth from their red LEDs), so a warmer white is a much dimmer lamp
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta

from .blocks import smoothstep


def bed_and_wake(now: datetime, bed: datetime | None, wake: datetime | None, p: dict) -> tuple[datetime, datetime]:
    """Tonight's planned bedtime and wake time (sensor.bedtime_plan), or the bedtime_without_plan
    and wake_without_plan settings without a plan. Before noon the plan is still last night's, so
    "bed" is in the past and "wake" is this morning. now is local and aware"""
    if bed is not None and wake is not None:
        return bed, wake
    day = now.date()
    at = lambda hhmm: datetime.combine(day, time.fromisoformat(hhmm), now.tzinfo)  # noqa: E731
    return (at(p["bedtime_without_plan"]) - timedelta(days=0 if now.hour >= 12 else 1),
            at(p["wake_without_plan"]) + timedelta(days=1 if now.hour >= 12 else 0))


def calm_from(bed: datetime, p: dict) -> datetime:
    """When Calm starts: the hour (calm_before_bed_minutes) before that bedtime"""
    return bed - timedelta(minutes=p["calm_before_bed_minutes"])


def light_curve(now: datetime, elevation: float, cloud_pct: float, wind_down_hours: float,
                bed: datetime, wake: datetime, p: dict) -> dict:
    """{level (percent), kelvin, daylight and wind_down (0 to 1, for the record)}"""
    full = math.radians(p["daylight_full_elevation"])
    clear = min(max(math.sin(math.radians(elevation)) / math.sin(full), 0.0), 1.0)
    c = cloud_pct / 100
    d = clear * (1 - 0.75 * c ** 3.4)

    ramp = p["wind_down_ramp_minutes"] / 60
    if now >= wake:
        w = 0.0
    else:
        to_bed = (bed - now).total_seconds() / 3600
        w = smoothstep((wind_down_hours + ramp - to_bed) / ramp)

    dark = p["ambient_level_dark"]
    level = dark - (dark - p["ambient_level_daylight"]) * d
    level = level + (p["ambient_level_wind_down"] - level) * w
    h = now.hour + now.minute / 60
    k_day, k_eve = p["kelvin_morning"], p["kelvin_evening"]
    k = k_day - (k_day - k_eve) * smoothstep((h - 13) / 2)
    k = k + (k_eve - k) * w
    k = max(k, p["kelvin_floor"])
    return {"level": int(round(level)), "kelvin": int(round(k)), "daylight": round(d, 2), "wind_down": round(w, 2)}
