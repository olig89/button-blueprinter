from __future__ import annotations

from custom_components.button_blueprinter.core.gestures import Gesture
from custom_components.button_blueprinter.core.translate import Raw, from_event

from .fixtures import model


def test_hue_dimmer_short_release_is_a_tap_and_initial_press_is_ignored():
    slot = model("hue_dimmer").slot("button_2")
    assert from_event(slot, "short_release", {}) == Raw("up", "tap")
    assert from_event(slot, "long_press", {}) == Gesture("up", "long_press")
    assert from_event(slot, "repeat", {}) == Gesture("up", "long_press_repeat")
    assert from_event(slot, "initial_press", {}) is None
    assert from_event(slot, None, {}) is None


def test_tap_dial_turns_scale_hue_steps():
    slot = model("hue_tap_dial").slot("rotary")
    assert from_event(slot, "clock_wise", {"steps": 75}) == Gesture("dial", "turn_right", 5)
    assert from_event(slot, "counter_clock_wise", {"steps": 4}) == Gesture("dial", "turn_left", 1)


def test_bilresa_notches_are_steps():
    slot = model("ikea_bilresa_scroll_wheel").slot("channel_2")
    assert from_event(slot, "rotate_down", {"notches": 3}) == Gesture("channel_2", "turn_left", 3)
    assert from_event(slot, "hold", {}) == Gesture("channel_2", "long_press")


def test_nuimo_sign_picks_the_direction():
    slot = model("senic_nuimo").slot("control")
    assert from_event(slot, "rotate", {"delta": 25}) == Gesture("ring", "turn_right", 2)
    assert from_event(slot, "rotate", {"delta": -3}) == Gesture("ring", "turn_left", 1)
    assert from_event(slot, "rotate", {"delta": 0}) is None
    assert from_event(slot, "press", {}) == Raw("top", "down")
    assert from_event(slot, "swipe_left", {}) == Gesture("top", "swipe_left")


def test_cube_side_picks_the_face_and_angle_is_steps():
    slot = model("aqara_cube_t1_pro").slots[0]
    assert from_event(slot, "flip_to_side", {"side": 3}) == Gesture("face_3", "face_up")
    assert from_event(slot, "side_up", {"side": 6.0}) == Gesture("face_6", "face_up")
    assert from_event(slot, "flip90", {"side": 2, "action_from_side": 5}) == Gesture("face_2", "face_up")
    assert from_event(slot, "flip_to_side", {"side": 0}) is None  # not a face
    assert from_event(slot, "flip_to_side", {}) is None
    assert from_event(slot, "rotate_right", {"action_angle": 91.3}) == Gesture("rotate", "turn_right", 3)
    assert from_event(slot, "rotate_left", {"action_angle": -9.3}) == Gesture("rotate", "turn_left", 1)
    assert from_event(slot, "shake", {"side": 1}) == Gesture("cube", "shake")
    assert from_event(slot, "1_min_inactivity", {}) is None
