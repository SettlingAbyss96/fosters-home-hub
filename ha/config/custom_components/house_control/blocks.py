"""The control blocks: plain arithmetic, nothing about the house (docs/control.md, "The blocks").

They take their state in and hand it back out, so one function serves any number of loops, and each
is tested on its own in tests/test_blocks.py before anything depends on it. No Home Assistant in
here, so the tests run in a blink.
"""

from __future__ import annotations

import math


def bayes_step(b: float, stay: float, enter: float, ratio: float) -> float:
    """One step of a two-state Bayes filter. b is the belief the hidden state is "on" (asleep, say)
    a step ago. Predict with the transition chances, then correct with the evidence:

        prior = b * stay + (1 - b) * enter
        b'    = prior * ratio / (prior * ratio + (1 - prior))

    stay is the chance of staying in the state one more step, enter the chance of going into it
    from the other one, and ratio is P(what was seen | on) / P(what was seen | off). A ratio of 1
    is "saw nothing useful", and then it's pure prediction. Kept off 0 and 1, where it would never
    move again."""
    prior = b * stay + (1 - b) * enter
    num = prior * ratio
    den = num + (1 - prior)
    return round(min(max(num / den if den > 0 else prior, 0.0001), 0.9999), 6)


def schmitt(x: float, on: float, off: float, was_on: bool) -> bool:
    """A threshold with hysteresis: on at `on` and above, off at `off` and below, and in between it
    stays as it was, so a value sitting on the line doesn't chatter"""
    if x >= on:
        return True
    if x <= off:
        return False
    return was_on


def lowpass(prev: float | None, x: float, dt: float, tau: float) -> float:
    """First-order low-pass, discretised exactly: the output moves toward the input by
    1 - exp(-dt / tau), so an uneven update rate doesn't change the filter. Starts at the input"""
    if prev is None:
        return float(x)
    a = 1 - math.exp(-dt / max(tau, 0.001))
    return round(prev + a * (x - prev), 6)


def rate(prev: float, x: float, dt: float) -> float:
    """Change per second. It amplifies noise, so low-pass the signal first"""
    return round((x - prev) / max(dt, 0.001), 6)


def pid(sp: float, pv: float, state: dict | None, dt: float, kp: float, ki: float, kd: float,
        lo: float, hi: float) -> dict:
    """One PID step. state is what this returned last time (None to start). The integral only grows
    while the output isn't pinned at a limit (conditional integration, the simplest anti-windup),
    and the derivative is on the measurement, not the error, so a setpoint change doesn't kick the
    output. Returns {"u": output, "i": integral, "pv": measurement}"""
    s = state or {}
    err = sp - pv
    i = float(s.get("i", 0.0))
    last_pv = float(s.get("pv", pv))
    d = -(pv - last_pv) / max(dt, 0.001)
    i_new = i + err * dt
    u_try = kp * err + ki * i_new + kd * d
    pinned = (u_try > hi and err > 0) or (u_try < lo and err < 0)
    i_used = i if pinned else i_new
    u = kp * err + ki * i_used + kd * d
    return {"u": round(min(max(u, lo), hi), 4), "i": round(i_used, 6), "pv": float(pv)}


def smoothstep(x: float) -> float:
    """0 below 0, 1 above 1, and an S between with no corners at either end"""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)
