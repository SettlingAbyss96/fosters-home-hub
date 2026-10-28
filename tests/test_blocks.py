"""The control core's pieces on their own (ha/config/custom_components/house_control): the
arithmetic blocks, a PID loop closed around a simulated room, the arbiter's gate and its idea of a
hand at the switch, the light curve and one step of the asleep filter. Plain Python with any clock
the test likes, so they're known to work before anything real depends on them."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from custom_components.house_control.arbiter import Arbiter, real_change
from custom_components.house_control.asleep import Seen, asleep_next
from custom_components.house_control.blocks import bayes_step, lowpass, pid, schmitt
from custom_components.house_control.curve import bed_and_wake, calm_from, light_curve

from house import TZ

# the settings, as control.jinja has them (the bench reads the real ones; these are the defaults)
P = {"command_match_pct": 6, "command_settle_seconds": 10, "command_match_seconds": 120,
     "asleep_on": 0.85, "asleep_max": 0.99, "asleep_off": 0.35, "asleep_hazard_late": 0.008,
     "asleep_hazard_evening": 0.003, "asleep_hazard_early": 0.003, "asleep_hazard_day": 0.0003,
     "asleep_hazard_max": 0.3, "asleep_wake_hazard": 0.002, "asleep_activity_ratio": 0.05,
     "asleep_typing_ratio": 0.001, "ambient_level_dark": 80, "ambient_level_daylight": 50,
     "ambient_level_wind_down": 35, "kelvin_morning": 4000, "kelvin_evening": 2700, "kelvin_floor": 2700,
     "daylight_full_elevation": 35, "wind_down_ramp_minutes": 60, "calm_before_bed_minutes": 60,
     "bedtime_without_plan": "22:30", "wake_without_plan": "07:00"}
LOCAL = ZoneInfo(TZ)
T0 = 1_790_000_000.0


def test_bayes_step():
    # prior = 0.2 * 0.99 + 0.8 * 0.01 = 0.206, then 0.206 * 4 / (0.206 * 4 + 0.794)
    assert bayes_step(0.2, 0.99, 0.01, 4) == pytest.approx(0.50927, abs=1e-4)
    # no evidence and no transitions: nothing moves
    assert bayes_step(0.5, 1, 0, 1) == 0.5


def test_schmitt_doesnt_chatter():
    state, out = False, []
    for x in [0.84, 0.86, 0.5, 0.36, 0.34, 0.6]:
        state = schmitt(x, 0.85, 0.35, state)
        out.append(state)
    assert out == [False, True, True, True, False, False]


def test_lowpass_step_response():
    # from 0, a step to 100: one time constant in (10 steps of 6 s, tau 60 s) a first-order filter
    # is 63.2% of the way there
    y = 0.0
    for _ in range(10):
        y = lowpass(y, 100, 6, 60)
    assert y == pytest.approx(63.2, abs=0.2)


def simulate(setpoints, kp=2.0, ki=0.05, kd=0.0, dt=10.0, tau=120.0):
    """A first-order room: y moves toward the controller's output with a 2-minute time constant"""
    y, state, trace = 20.0, None, []
    for sp in setpoints:
        state = pid(sp, y, state, dt, kp, ki, kd, 0, 100)
        y += (state["u"] - y) * (dt / tau)
        trace.append((y, state["u"]))
    return trace


def test_pid_settles_without_offset():
    trace = simulate([50.0] * 150)
    y, _ = trace[-1]
    assert y == pytest.approx(50.0, abs=0.5), "the integral takes the offset out"
    assert all(0 <= u <= 100 for _, u in trace)


def test_pid_doesnt_wind_up():
    # ask for the impossible for a long time, then something reasonable: with windup the integral
    # would have piled up and the room would sail far past 50
    trace = simulate([150.0] * 60 + [50.0] * 150)
    after = [y for y, _ in trace[60:]]
    assert max(after) < 105, "no big overshoot from a wound-up integral"
    assert after[-1] == pytest.approx(50.0, abs=1.0)


def test_the_gate():
    a = Arbiter()
    a.hold("light.lamp", 2, 180, "manual", T0)
    assert a.holding("light.lamp", 4, False, T0 + 60), "a look can't move a light set by hand"
    assert a.holding("light.lamp", 2, False, T0 + 60) is None, "equal goes: the newest wins"
    assert a.holding("light.lamp", 4, True, T0 + 60) is None, "you asking for a mode does"
    assert a.holding("light.lamp", 4, False, T0 + 181 * 60) is None, "and the hold runs out"
    a.hold("light.bedroom", 1, 75, "wake-up", T0)
    assert a.holding("light.bedroom", 2, True, T0 + 60), "nothing overrides the alarm"
    a.release("all", T0 + 60)
    assert "light.bedroom" in a.holds and "light.lamp" not in a.holds, "letting go of everything but the alarm"


def test_a_light_reporting_back_is_explained_and_a_hand_isnt():
    a = Arbiter()
    kw = {"tolerance_pct": 6, "settle_seconds": 10, "match_seconds": 120}
    a.command("light.lamp", 80, 30, 60, "look evening", T0)
    assert a.explained("light.lamp", True, round(50 * 2.55), T0 + 5, **kw), "on the way from 30 to 80"
    assert not a.explained("light.lamp", True, 255, T0 + 5, **kw), "100% is nowhere on the way"
    assert a.explained("light.lamp", True, round(80 * 2.55), T0 + 100, **kw), "there, a bit late"
    assert not a.explained("light.lamp", False, None, T0 + 100, **kw), "off is a person"
    assert not a.explained("light.other", True, 255, T0, **kw), "nothing was asked of it"
    assert real_change(True, 200, True, 210) and not real_change(True, 202, True, 203)


def test_the_curve_follows_the_day():
    day = datetime(2026, 10, 13, tzinfo=LOCAL)
    bed, wake = day.replace(hour=21, minute=40), day.replace(hour=5, minute=25) + timedelta(days=1)
    noon = light_curve(day.replace(hour=13), 50, 0, 3, bed, wake, P)
    assert noon["level"] == 50 and noon["kelvin"] == 4000, "full sun: the windows do the work"
    dusk = light_curve(day.replace(hour=17, minute=30), -5, 50, 3, bed, wake, P)
    assert dusk["level"] == 80 and dusk["kelvin"] == 2700
    late = light_curve(day.replace(hour=19, minute=40), -20, 50, 3, bed, wake, P)
    assert late["level"] == 35 and late["wind_down"] == 1.0, "three hours before bed it's all wind-down"
    assert calm_from(bed, P) == day.replace(hour=20, minute=40)


def test_without_a_plan_the_curve_has_its_own_bedtime():
    morning = datetime(2026, 10, 13, 9, tzinfo=LOCAL)
    bed, wake = bed_and_wake(morning, None, None, P)
    assert bed == datetime(2026, 10, 12, 22, 30, tzinfo=LOCAL), "before noon it's last night's"
    assert wake == datetime(2026, 10, 13, 7, tzinfo=LOCAL)


def quiet_night(**kw):
    seen = {"hour": 23, "quiet_minutes": 60, "active": False, "typing": False, "home": True, "night": True,
            "lights_on": False, "on_charger": True, "focus": False, "tv_picture": False,
            "bedroom_door_shut": False, "waking_up": False}
    return Seen(**{**seen, **kw})


def test_the_filter_takes_a_while_and_a_sign_of_life_pulls_it_back():
    b, minutes = 0.05, 0
    while b < 0.85:
        b = asleep_next(b, quiet_night(), P)["b"]
        minutes += 1
    assert 2 < minutes < 60, minutes
    assert asleep_next(b, quiet_night(active=True), P)["b"] < 0.5, "the Hub seeing someone is twenty times likelier awake"
    assert asleep_next(0.9, quiet_night(home=False), P)["b"] < 0.01, "out is never asleep"
    assert asleep_next(0.5, quiet_night(typing=True), P)["enter"] == 0, "typing isn't falling asleep"
