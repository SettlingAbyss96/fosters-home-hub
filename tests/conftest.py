"""Scenario tests for the house's logic, on the real Home Assistant (see house.py)."""

import pytest
from homeassistant.helpers import template as ha_template

from house import House

# Every test builds a new Home Assistant, and every new one compiled the same 632 templates from
# scratch, about a second of each test's two. The compiled code doesn't belong to any one Home
# Assistant (it's handed its environment when it runs), so one copy does for the whole run
_COMPILED: dict = {}
_compile = ha_template.TemplateEnvironment.compile


def _compile_once(self, source, name=None, filename=None, raw=False, defer_init=False):
    if not isinstance(source, str) or name is not None or filename is not None or raw or defer_init:
        return _compile(self, source, name, filename, raw, defer_init)
    key = (self.limited, source)
    if key not in _COMPILED:
        _COMPILED[key] = _compile(self, source)
    code = self.template_cache[source] = self.compiled_code_pin[source] = _COMPILED[key]
    return code


ha_template.TemplateEnvironment.compile = _compile_once


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
