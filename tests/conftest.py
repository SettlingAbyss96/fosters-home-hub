"""Scenario tests for the house's logic, on the real Home Assistant (see house.py)."""

import pytest

from house import House


@pytest.fixture
def house_at(hass, freezer):
    """house = await house_at("2026-10-13 04:50", {"input_select.house_mode": "Night"})"""

    async def build(at: str, states: dict | None = None) -> House:
        return await House.build(hass, freezer, at, states)

    return build


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The house always has timers running (the arrival timers, script delays, every-minute ticks)"""
    return True


# things that are broken on the bench rather than in the house: the weather sensors want forecasts
# from a weather service the bench doesn't have
BENCH_ONLY = ("today_s_weather", "weather.forecast_home")


@pytest.fixture(autouse=True)
def no_silent_errors(caplog, request):
    """An automation or script that errors usually just looks like it did nothing, and a test that
    expects nothing passes. Any error, failed condition or undefined-variable warning from the
    house's own logic fails the test instead (found the hard way: the by-hand detector errored on
    every light without a brightness, and its tests passed)"""
    yield
    allowed = [m.args[0] for m in request.node.iter_markers("expect_errors")]
    bad = []
    for r in caplog.get_records("call"):
        name, msg = r.name, r.getMessage()
        if any(b in msg for b in BENCH_ONLY) or any(a in msg for a in allowed):
            continue
        ours = name.startswith(("homeassistant.components.automation", "homeassistant.components.script",
                                "homeassistant.components.template", "homeassistant.helpers.template"))
        if ours and (r.levelno >= 40 or "Error evaluating condition" in msg or "Template variable" in msg):
            bad.append(f"{name}: {msg[:300]}")
    assert not bad, "the house's logic logged errors:\n" + "\n".join(bad)


def pytest_configure(config):
    config.addinivalue_line("markers", "expect_errors(text): errors containing text are part of the test")
