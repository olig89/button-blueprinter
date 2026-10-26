from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core import knx
from custom_components.button_blueprinter.core.export import to_automation
from custom_components.button_blueprinter.core.switches import Switch, SwitchError, check, led_value, new_id

from .fixtures import SMALL_BATHROOM, icon_sets, model


def small_bathroom() -> Switch:
    four = model("schneider_mtn6185")
    kx = {"tap": "6/0/40", "hold": "6/1/40", "led": "6/2/40", "address": "1.1.31"}
    bindings, _ = knx.read_automation(four, kx, SMALL_BATHROOM)
    return Switch(
        id="small_bathroom",
        name="Small Bathroom",
        model=four.id,
        area_id="small_bathroom",
        knx=kx,
        fixed={"b2": {"long_press": "Room lights on (KNX)"}, "b4": {"long_press": "Room lights off (KNX)"}},
        bindings={c: {g: {"actions": a} for g, a in gs.items()} for c, gs in bindings.items()},
    )


def test_a_good_switch_passes_and_round_trips():
    s = small_bathroom()
    check(s, model("schneider_mtn6185"))
    assert Switch.from_dict(s.as_dict()).as_dict() == s.as_dict()
    assert s.mode == "dry_run"


def test_fixed_and_bound_together_is_refused():
    s = small_bathroom()
    s.bindings["b2"]["long_press"] = {"menu": {"kind": "toggle", "entities": ["light.x"]}}
    with pytest.raises(SwitchError, match="fixed"):
        check(s, model("schneider_mtn6185"))


def test_a_gesture_the_model_lacks_is_refused():
    s = small_bathroom()
    s.bindings["b1"]["turn_right"] = {"menu": {"kind": "toggle", "entities": ["light.x"]}}
    with pytest.raises(SwitchError, match="can't do"):
        check(s, model("schneider_mtn6185"))


def test_bindings_are_checked():
    s = small_bathroom()
    s.bindings["b1"]["press"] = {"menu": {"kind": "toggle", "entities": ["shell_command.x"]}}
    with pytest.raises(SwitchError):
        check(s, model("schneider_mtn6185"))


def test_event_switch_needs_event_entities():
    s = Switch(id="d", name="Dial", model="hue_tap_dial", entities={"rotary": "sensor.x"})
    with pytest.raises(SwitchError, match="event entity"):
        check(s, model("hue_tap_dial"))


def test_inserts_come_from_the_insert_sheets():
    s = small_bathroom()
    s.looks = {"b1": {"icon": "bulb_on", "label": "ceiling"}, "b3": {"icon": "message"}}
    check(s, model("schneider_mtn6185"), icon_sets())
    s.looks = {"b1": {"icon": "gaming"}}  # on the display set, not on an insert sheet
    with pytest.raises(SwitchError, match="isn't one of this switch's icons"):
        check(s, model("schneider_mtn6185"), icon_sets())
    s.looks = {"b1": {"icon": "mdi:lightbulb"}}
    with pytest.raises(SwitchError, match="isn't one of"):
        check(s, model("schneider_mtn6185"), icon_sets())


def office(looks):
    return Switch(id="o", name="Office", model="schneider_mtn619x", knx={"tap": "6/0/60", "led": "6/2/60"}, looks=looks)


def test_display_looks_are_what_the_plate_can_show():
    good = {"b3": {"label": "Working", "show": "icon_name", "icon_on": "working", "icon_off": "working", "colour_on": "green", "colour_off": "white"}}
    check(office(good), model("schneider_mtn619x"), icon_sets())
    for bad, why in (
        ({"b1": {"icon_on": "message"}}, "can't be shown on this display"),
        ({"b1": {"icon_on": "mdi:lightbulb"}}, "isn't one of"),
        ({"b1": {"label": "Thirteen chars"}}, "fits 12"),
        ({"b1": {"colour_on": "purple"}}, "colours are"),
        ({"b1": {"show": "big"}}, "Show is"),
        ({"b1": {"icon": "bulb_on"}}, "A look here is"),
    ):
        with pytest.raises(SwitchError, match=why):
            check(office(bad), model("schneider_mtn619x"), icon_sets())


def test_an_icon_set_must_be_loaded_to_check():
    with pytest.raises(SwitchError, match="isn't loaded"):
        check(office({"b1": {"icon_on": "bulb_on"}}), model("schneider_mtn619x"), {})


def test_other_models_still_take_any_mdi_icon():
    s = Switch(id="d", name="Dimmer", model="hue_dimmer", entities={"button_1": "event.x_button_1"}, looks={"top": {"icon": "mdi:power"}})
    check(s, model("hue_dimmer"), icon_sets())
    s.looks = {"top": {"icon": "lightbulb"}}
    with pytest.raises(SwitchError, match="icon name"):
        check(s, model("hue_dimmer"), icon_sets())


def test_new_ids_and_led_values():
    assert new_id("Alex's Office", set()) == "alexs_office"
    assert new_id("Alex's Office", {"alexs_office"}) == "alexs_office_2"
    assert led_value({"entity_id": "binary_sensor.x"}, "on") == 1
    assert led_value({"entity_id": "binary_sensor.x", "state": "playing"}, "paused") == 0
    assert led_value({"entity_id": "x"}, None) == 0


def test_export_gives_a_working_shape():
    s = small_bathroom()
    s.bindings["b1"]["double_press"] = {"menu": {"kind": "turn_off", "entities": ["light.small_bathroom_ceiling"]}}
    auto = to_automation(s, model("schneider_mtn6185"))
    ids = {t["id"] for t in auto["triggers"]}
    assert "b1__press" in ids and "b2__press" in ids and "b1__long_press" in ids
    assert {t["destination"][0] for t in auto["triggers"]} >= {"6/0/40", "6/1/40"}
    assert "Double tap" in auto["description"]


def test_export_of_a_dial():
    s = Switch(
        id="d",
        name="Dial",
        model="senic_nuimo",
        entities={"control": "event.nuimo_control_button"},
        bindings={"ring": {"turn_right": {"menu": {"kind": "brighter", "entities": ["light.a"]}}}},
    )
    auto = to_automation(s, model("senic_nuimo"))
    opt = auto["actions"][0]["choose"][0]
    assert "> 0" in opt["conditions"][1]["value_template"]
    assert opt["sequence"][0] == {"variables": {"steps": "{{ (trigger.to_state.attributes.delta | float(0) | abs / 10.0) | round | int | max(1) }}"}}


def cube(**extra) -> Switch:
    return Switch(
        id="cube",
        name="Cube",
        model="aqara_cube_t1_pro",
        device="dev1",
        **{
            "bindings": {
                "face_2": {"face_up": {"menu": {"kind": "colour", "entities": ["light.lamp"], "colour": "orange"}}},
                "rotate": {"turn_right": {"menu": {"kind": "brighter", "entities": ["light.lamp"]}}},
            },
            **extra,
        },
    )


def test_a_cube_keeps_its_device_and_takes_no_entities():
    s = cube()
    check(s, model("aqara_cube_t1_pro"))
    assert Switch.from_dict(s.as_dict()).device == "dev1"
    with pytest.raises(SwitchError, match="Zigbee2MQTT"):
        check(cube(entities={"x": "event.x"}), model("aqara_cube_t1_pro"))


def test_a_cube_exports_as_mqtt_triggers():
    auto = to_automation(cube(), model("aqara_cube_t1_pro"), "zigbee2mqtt/Cube")
    assert {t["payload"] for t in auto["triggers"]} == {"flip_to_side", "side_up", "flip90", "flip180", "rotate_right"}
    assert all(t["trigger"] == "mqtt" and t["topic"] == "zigbee2mqtt/Cube" for t in auto["triggers"])
    face = next(o for o in auto["actions"][0]["choose"] if o["conditions"][0]["id"] == "face_2__face_up")
    assert "side | string == '2'" in face["conditions"][1]["value_template"]
    turn = next(o for o in auto["actions"][0]["choose"] if o["conditions"][0]["id"] == "rotate__turn_right")
    assert "action_angle" in turn["sequence"][0]["variables"]["steps"]
    assert "Not exported" not in auto["description"]


def test_put_back_is_kept_and_put_back_now_needs_it():
    s = cube(put_back={"minutes": "30", "controls": ["face_1"]})
    check(s, model("aqara_cube_t1_pro"))
    assert s.put_back == {"minutes": 30, "controls": ["face_1"]}
    assert Switch.from_dict(s.as_dict()).put_back == s.put_back
    now = {"cube": {"shake": {"menu": {"kind": "put_back"}}}}
    with pytest.raises(SwitchError, match="putting lights back"):
        check(cube(bindings=now), model("aqara_cube_t1_pro"))
    check(cube(bindings=now, put_back={"minutes": 30}), model("aqara_cube_t1_pro"))
