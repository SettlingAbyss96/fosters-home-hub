"""The control blocks (custom_templates/control.jinja) on their own: the arithmetic, and a PID loop
closed around a simulated room, so they're known to work before anything real depends on them."""

import json

import pytest
from homeassistant.helpers.template import Template

TUESDAY = "2026-10-13"


def render(house, source: str) -> str:
    return Template(source, house.hass).async_render(parse_result=False).strip()


@pytest.fixture
async def house(house_at):
    return await house_at(f"{TUESDAY} 12:00")


async def test_bayes_step(house):
    # prior = 0.2 * 0.99 + 0.8 * 0.01 = 0.206, then 0.206 * 4 / (0.206 * 4 + 0.794)
    out = float(render(house, "{% from 'control.jinja' import bayes_step %}{{ bayes_step(0.2, 0.99, 0.01, 4) }}"))
    assert out == pytest.approx(0.50927, abs=1e-4)
    # no evidence and no transitions: nothing moves
    assert float(render(house, "{% from 'control.jinja' import bayes_step %}{{ bayes_step(0.5, 1, 0, 1) }}")) == 0.5


async def test_schmitt_doesnt_chatter(house):
    state, out = "off", []
    for x in [0.84, 0.86, 0.5, 0.36, 0.34, 0.6]:
        state = render(house, f"{{% from 'control.jinja' import schmitt %}}{{{{ schmitt({x}, 0.85, 0.35, '{state}') }}}}")
        out.append(state)
    assert out == ["off", "on", "on", "on", "off", "off"]


async def test_lowpass_step_response(house):
    # from 0, a step to 100: one time constant in (10 steps of 6 s, tau 60 s) a first-order filter
    # is 63.2% of the way there
    y = 0.0
    for _ in range(10):
        y = float(render(house, f"{{% from 'control.jinja' import lowpass %}}{{{{ lowpass({y}, 100, 6, 60) }}}}"))
    assert y == pytest.approx(63.2, abs=0.2)


def simulate(house, setpoints, kp=2.0, ki=0.05, kd=0.0, dt=10.0, tau=120.0):
    """A first-order room: y moves toward the controller's output with a 2-minute time constant"""
    y, state, trace = 20.0, "", []
    for sp in setpoints:
        out = json.loads(render(house, "{% from 'control.jinja' import pid %}"
                                f"{{{{ pid({sp}, {y}, '{state}', {dt}, {kp}, {ki}, {kd}, 0, 100) }}}}"))
        state = json.dumps(out)
        y += (out["u"] - y) * (dt / tau)
        trace.append((y, out["u"]))
    return trace


async def test_pid_settles_without_offset(house):
    trace = simulate(house, [50.0] * 150)
    y, u = trace[-1]
    assert y == pytest.approx(50.0, abs=0.5), "the integral takes the offset out"
    assert all(0 <= u <= 100 for _, u in trace)


async def test_pid_doesnt_wind_up(house):
    # ask for the impossible for a long time, then something reasonable: with windup the integral
    # would have piled up and the room would sail far past 50
    trace = simulate(house, [150.0] * 60 + [50.0] * 150)
    after = [y for y, _ in trace[60:]]
    assert max(after) < 105, "no big overshoot from a wound-up integral"
    assert after[-1] == pytest.approx(50.0, abs=1.0)
