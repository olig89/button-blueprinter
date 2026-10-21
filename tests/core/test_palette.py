from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core.palette import MenuError, check, from_actions, scenes_of, to_actions


def test_toggle_one_light_is_a_plain_toggle():
    assert to_actions(check({"kind": "toggle", "entities": ["light.a"]})) == [
        {"action": "light.toggle", "target": {"entity_id": "light.a"}}
    ]


def test_toggle_several_is_any_on_all_off():
    acts = to_actions(check({"kind": "toggle", "entities": ["light.a", "light.b"]}))
    assert acts[0]["if"][0]["match"] == "any"
    assert from_actions(acts) == {"kind": "toggle", "entities": ["light.a", "light.b"]}


def test_round_trips():
    for choice in (
        {"kind": "turn_on", "entities": ["light.a"], "brightness": 100},
        {"kind": "turn_off", "entities": ["light.a", "switch.b"]},
        {"kind": "toggle", "entities": ["light.a"]},
    ):
        assert from_actions(to_actions(check(choice))) == check(choice)


def test_scene_again_off_uses_the_switch_scenes():
    acts = to_actions(check({"kind": "scene", "scene": "scene.office_bright", "again_off": True}))
    assert "switch_scenes" in acts[0]["variables"]["last_scene"]
    assert acts[1]["else"] == [{"action": "scene.turn_on", "target": {"entity_id": "scene.office_bright"}}]
    plain = to_actions(check({"kind": "scene", "scene": "scene.x"}))
    assert plain == [{"action": "scene.turn_on", "target": {"entity_id": "scene.x"}}]


def test_dimming_scales_by_steps():
    acts = to_actions(check({"kind": "dimmer", "entities": ["light.a"], "step": 5}))
    assert acts[0]["data"]["brightness_step_pct"] == "{{ -5 * (steps | int(1)) }}"


def test_volume_repeats_per_step():
    acts = to_actions(check({"kind": "media", "entity": "media_player.office", "command": "volume_up"}))
    assert acts[0]["repeat"]["count"] == "{{ steps | int(1) }}"


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "shell", "command": "rm"},
        {"kind": "toggle", "entities": []},
        {"kind": "toggle", "entities": ["shell_command.wipe"]},
        {"kind": "brighter", "entities": ["switch.a"]},
        {"kind": "turn_on", "entities": ["light.a"], "brightness": 300},
        {"kind": "media", "entity": "media_player.a", "command": "eject"},
        {"kind": "toggle", "entities": ["light.a"], "extra": 1},
        "toggle",
    ],
)
def test_the_menu_refuses_anything_else(bad):
    with pytest.raises(MenuError):
        check(bad)


def test_scenes_of_lists_each_scene_once():
    b = {
        "b1": {"press": {"menu": {"kind": "scene", "scene": "scene.a"}}},
        "b3": {"press": {"menu": {"kind": "scene", "scene": "scene.b"}}, "long_press": {"menu": {"kind": "scene", "scene": "scene.a"}}},
        "b5": {"press": {"actions": [{"action": "scene.turn_on"}]}},
    }
    assert scenes_of(b) == ["scene.a", "scene.b"]


def test_unknown_actions_are_not_a_menu_choice():
    assert from_actions([{"action": "notify.mobile", "data": {"message": "x"}}]) is None
    assert from_actions([{"action": "light.toggle", "target": {"entity_id": "{{ x }}"}}]) is None


def test_vacuum_cleans_the_area_in_its_mode_or_sends_it_home():
    acts = to_actions(check({"kind": "vacuum", "vacuum": "vacuum.hoovie", "area": "kitchen", "mode": "vac_and_mop"}))
    step = acts[0]
    assert step["if"] == [{"condition": "state", "entity_id": "vacuum.hoovie", "state": "cleaning"}]
    assert step["then"] == [{"action": "vacuum.return_to_base", "target": {"entity_id": "vacuum.hoovie"}}]
    mode, clean = step["else"]
    assert mode["then"][0]["target"] == {"entity_id": "select.hoovie_cleaning_mode"}
    assert mode["then"][0]["data"] == {"option": "vac_and_mop"}
    assert "select.hoovie_cleaning_mode" in mode["if"][0]["value_template"]
    assert clean == {"action": "vacuum.clean_area", "target": {"entity_id": "vacuum.hoovie"}, "data": {"cleaning_area_id": ["kitchen"]}}


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "vacuum", "vacuum": "vacuum.hoovie", "area": "kitchen", "mode": "polish"},
        {"kind": "vacuum", "vacuum": "vacuum.hoovie", "area": "", "mode": "vacuum"},
        {"kind": "vacuum", "vacuum": "vacuum.hoovie", "area": "Kitchen'}}", "mode": "vacuum"},
        {"kind": "vacuum", "vacuum": "light.a", "area": "kitchen", "mode": "vacuum"},
    ],
)
def test_vacuum_needs_a_robot_an_area_and_a_mode(bad):
    with pytest.raises(MenuError):
        check(bad)


def test_colour_keeps_brightness_and_has_white_back():
    assert to_actions(check({"kind": "colour", "entities": ["light.lamp"], "colour": "red"})) == [
        {"action": "light.turn_on", "target": {"entity_id": ["light.lamp"]}, "data": {"rgb_color": [255, 0, 0]}}
    ]
    assert to_actions(check({"kind": "colour", "entities": ["light.lamp"], "colour": "warm_white"}))[0]["data"] == {"color_temp_kelvin": 2700}
    with pytest.raises(MenuError):
        check({"kind": "colour", "entities": ["light.lamp"], "colour": "indigo"})
    with pytest.raises(MenuError):
        check({"kind": "colour", "entities": ["switch.fan"], "colour": "red"})
