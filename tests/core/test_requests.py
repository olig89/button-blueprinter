from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core.requests import changed_where, full_look, same_look, steps
from custom_components.button_blueprinter.core.switches import Switch, SwitchError, check

from .fixtures import icon_sets, model

EIGHT = model("schneider_mtn619x")
FOUR = model("schneider_mtn6185")
SET = icon_sets()["schneider_dlife"]
PLATE = {"label": "Button 3", "show": "icon", "icon_on": "working", "icon_off": "working", "colour_on": "green", "colour_off": "white"}


def test_where_a_look_is_changed():
    assert changed_where(EIGHT) == "ets"
    assert changed_where(FOUR) == "insert"
    assert changed_where(model("hue_dimmer")) is None


def test_defaults_count_as_set():
    assert full_look(EIGHT, {})["icon_on"] == "bulb_on"
    assert same_look(EIGHT, {}, {"show": "icon", "icon_on": "bulb_on", "icon_off": "bulb_off", "colour_on": "white", "colour_off": "green"})
    assert not same_look(EIGHT, PLATE, {**PLATE, "colour_on": "red"})


def test_an_insert_note_is_not_part_of_the_plate():
    assert same_look(FOUR, {"icon": "bulb_on", "label": "ceiling"}, {"icon": "bulb_on"})
    assert not same_look(FOUR, {"icon": "bulb_on"}, {"icon": "bulb_off"})


def test_ets_steps_name_the_function_and_settings():
    wanted = {**PLATE, "label": "Dimmed", "show": "icon_name", "colour_on": "blue"}
    got = steps(EIGHT, "b3", PLATE, wanted, SET)
    assert got["where"] == "ets" and got["function"] == "Function 3"
    assert got["changes"] == [
        {"setting": "Indication type", "from": "Icon only", "to": "Icon + name of the channel"},
        {"setting": "Name of the channel", "from": "Button 3", "to": "Dimmed"},
        {"setting": "Colour for status on", "from": "Green", "to": "Blue"},
    ]


def test_insert_steps_name_the_insert():
    got = steps(FOUR, "b1", {}, {"icon": "ceiling_lamp"}, SET)
    assert got["changes"] == [{"setting": "Insert", "from": "(none)", "to": "Ceiling lamp"}]


def test_wanted_looks_are_checked_like_looks():
    s = Switch(id="o", name="Office", model="schneider_mtn619x", knx={"tap": "6/0/60"}, wanted={"b1": {"look": {"colour_on": "purple"}}})
    with pytest.raises(SwitchError, match="colours are"):
        check(s, EIGHT, icon_sets())
    s.wanted = {"b1": {"look": {"colour_on": "blue"}, "by": "Alex"}}
    check(s, EIGHT, icon_sets())
    assert Switch.from_dict(s.as_dict()).wanted == s.wanted


def test_switches_without_outside_looks_take_no_requests():
    s = Switch(id="d", name="Dimmer", model="hue_dimmer", entities={"button_1": "event.x_button_1"}, wanted={"top": {"look": {"icon": "mdi:power"}}})
    with pytest.raises(SwitchError, match="set here directly"):
        check(s, model("hue_dimmer"), icon_sets())
