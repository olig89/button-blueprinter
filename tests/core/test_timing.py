from __future__ import annotations

from custom_components.button_blueprinter.core.timing import Timing


def names(gestures):
    return [g.gesture for g in gestures]


def test_tap_fires_at_once_without_a_double_binding():
    t = Timing()
    assert names(t.feed(0.0, "b1", "tap", wants_double=False)) == ["press"]
    assert t.next_deadline() is None


def test_tap_waits_for_a_double_when_one_is_bound():
    t = Timing(double_window=0.4)
    assert t.feed(0.0, "b1", "tap", wants_double=True) == []
    assert t.next_deadline() == 0.4
    assert names(t.due(0.39)) == []
    assert names(t.due(0.4)) == ["press"]


def test_two_taps_make_a_double():
    t = Timing()
    t.feed(0.0, "b1", "tap", wants_double=True)
    assert names(t.feed(0.3, "b1", "tap", wants_double=True)) == ["double_press"]
    assert t.next_deadline() is None


def test_taps_on_different_controls_stay_apart():
    t = Timing()
    t.feed(0.0, "b1", "tap", wants_double=True)
    assert names(t.feed(0.1, "b2", "tap", wants_double=False)) == ["press"]
    assert [(g.control, g.gesture) for g in t.due(0.5)] == [("b1", "press")]


def test_down_up_short_is_a_tap():
    t = Timing()
    t.feed(0.0, "top", "down")
    assert names(t.feed(0.2, "top", "up")) == ["press"]


def test_held_down_is_a_hold_that_repeats_then_releases():
    t = Timing(hold_after=0.5, repeat_every=0.3)
    t.feed(0.0, "top", "down")
    assert names(t.due(0.5)) == ["long_press"]
    assert names(t.due(0.8)) == ["long_press_repeat"]
    assert names(t.due(1.4)) == ["long_press_repeat", "long_press_repeat"]
    assert names(t.feed(1.5, "top", "up")) == ["long_press_release"]
    assert t.next_deadline() is None


def test_repeats_stop_at_the_safety_limit():
    t = Timing(hold_after=0.5, repeat_every=0.1, max_repeats=3)
    t.feed(0.0, "top", "down")
    out = []
    now = 0.0
    while (deadline := t.next_deadline()) is not None and now < 10:
        now = deadline
        out += names(t.due(now))
    assert out == ["long_press", *["long_press_repeat"] * 3]
    assert t.next_deadline() is None


def test_down_then_hold_after_a_waiting_tap_flushes_the_tap():
    t = Timing()
    t.feed(0.0, "top", "down")
    t.feed(0.1, "top", "up", wants_double=True)  # first tap, waiting for a second
    t.feed(0.2, "top", "down")
    assert names(t.due(0.75)) == ["press", "long_press"]


def test_stray_up_is_ignored():
    assert Timing().feed(0.0, "top", "up") == []
