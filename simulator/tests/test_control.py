"""The Python port must agree with firmware/common/control.h (see firmware/tests)."""

import math

from simulator import control as c


def test_decide_precedence():
    assert c.decide("auto", False, True, None, None) == c.Decision(True, "auto")
    assert c.decide("on", False, False, None, None) == c.Decision(True, "manual")
    assert c.decide("off", True, True, None, None) == c.Decision(True, "fallback")
    assert c.decide("on", False, False, "I-1", None) == c.Decision(False, "interlock", "I-1")
    assert c.decide("auto", False, False, "I-9", None) == c.Decision(False, "auto")
    assert c.decide("off", False, False, None, "I-5") == c.Decision(True, "interlock", "I-5")
    assert c.decide("on", False, False, "I-1", "I-5") == c.Decision(False, "interlock", "I-1")
    assert c.decide("auto", False, False, "I-1", "I-5") == c.Decision(False, "auto")


def test_windows_thermostats_and_cycles():
    assert c.in_window(0, 1200, 360) and not c.in_window(720, 1200, 360)
    assert not c.in_window(5, 600, 600)
    assert c.heat_demand(True, math.nan, 20, 0.5) and not c.heat_demand(False, 20.2, 20, 0.5)
    assert c.exhaust_demand(False, math.nan, 80, 28, 70)
    assert not c.exhaust_demand(True, 25, 60, 28, 70)
    assert c.cycle_on(899, 900, 2700) and not c.cycle_on(900, 900, 2700)


def test_overtemp_latches():
    hot = c.OverTemp()
    assert not hot.update(36, 35, 30, 100, 120)
    assert hot.update(36, 35, 30, 30, 120)
    assert hot.update(32, 35, 30, 1, 120) and hot.update(math.nan, 35, 30, 1, 120)
    assert not hot.update(29, 35, 30, 1, 120)


def test_doser_limits():
    d = c.Doser(20, 600, 2)
    assert sum(d.step(500 if i == 0 else 0, None, 1) for i in range(60)) == 20
    assert d.step(5, None, 1) == 0 and d.refused == "busy"
    for _ in range(600):
        d.step(0, None, 1)
    assert d.step(5, "I-12", 1) == 0 and d.refused == "I-12"
    assert d.step(5, None, 1) == 1
    assert d.step(0, "I-10", 1) == 0 and d.refused == "I-10"  # aborted mid-dose
    for _ in range(600):
        d.step(0, None, 1)
    assert d.step(5, None, 1) == 0 and d.refused == "daily-cap"
