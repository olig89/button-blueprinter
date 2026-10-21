from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core.putback import PutBackError, applies, check, look, restore_actions, touched


def test_the_setting_is_opt_in_and_checked():
    assert check(None, ["a"]) is None
    assert check({"minutes": ""}, ["a"]) is None
    assert check({"minutes": "30"}, ["a", "b"]) == {"minutes": 30}
    assert check({"minutes": 5, "controls": ["b", "b"]}, ["a", "b"]) == {"minutes": 5, "controls": ["b"]}
    with pytest.raises(PutBackError, match="no control"):
        check({"minutes": 5, "controls": ["z"]}, ["a"])
    with pytest.raises(PutBackError, match="1 to"):
        check({"minutes": 0.5}, ["a"])
    with pytest.raises(PutBackError, match="1 to"):
        check({"minutes": 5000}, ["a"])


def test_applies_to_all_controls_or_the_chosen_ones():
    assert not applies(None, "a")
    assert applies({"minutes": 5}, "a")
    assert applies({"minutes": 5, "controls": ["b"]}, "b")
    assert not applies({"minutes": 5, "controls": ["b"]}, "a")


def test_only_menu_choices_say_what_they_touch():
    assert touched({"menu": {"kind": "colour", "entities": ["light.a"], "colour": "red"}}) == ["light.a"]
    assert touched({"menu": {"kind": "scene", "scene": "scene.x"}}) == ["scene.x"]
    assert touched({"menu": {"kind": "script", "script": "script.x"}}) == []
    assert touched({"actions": [{"action": "light.turn_on"}]}) == []


def test_a_light_is_saved_by_its_colour_mode_and_put_back():
    on = {"brightness": 120, "color_mode": "xy", "xy_color": (0.3, 0.4), "hs_color": (30, 50)}
    saved = look("light.a", "on", on)
    assert saved == {"state": "on", "brightness": 120, "xy_color": [0.3, 0.4]}
    assert restore_actions("light.a", saved) == [
        {"action": "light.turn_on", "target": {"entity_id": "light.a"}, "data": {"brightness": 120, "xy_color": [0.3, 0.4]}}
    ]
    warm = look("light.a", "on", {"brightness": 50, "color_mode": "color_temp", "color_temp_kelvin": 2700})
    assert warm["color_temp_kelvin"] == 2700
    assert look("light.a", "off", on) == {"state": "off"}
    assert restore_actions("light.a", {"state": "off"}) == [{"action": "light.turn_off", "target": {"entity_id": "light.a"}}]
    assert look("light.a", "unavailable", {}) is None
    assert restore_actions("switch.b", {"state": "on"}) == [{"action": "switch.turn_on", "target": {"entity_id": "switch.b"}}]
