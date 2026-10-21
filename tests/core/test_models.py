from __future__ import annotations

import pytest
import yaml

from custom_components.button_blueprinter.core.models import ModelError, parse_model

from .fixtures import MODELS_DIR, model


def test_every_shipped_model_loads():
    files = sorted(MODELS_DIR.glob("*.yaml"))
    assert len(files) >= 7
    for path in files:
        m = parse_model(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
        assert m.id == path.stem
        assert m.controls


def test_knx_models_number_their_controls():
    four = model("schneider_mtn6185")
    # This model's numbering: button 2 is bottom left, offset 1.
    assert [(c.id, c.knx) for c in four.controls] == [("b1", 0), ("b3", 2), ("b2", 1), ("b4", 3)]
    assert four.control("b2").geometry["y"] > four.control("b1").geometry["y"]
    eight = model("schneider_mtn619x")
    assert [c.knx for c in eight.controls] == list(range(8))


def test_event_models_find_their_entities():
    dial = model("hue_tap_dial")
    assert dial.slot("rotary").matches("event.office_dial_rotary")
    assert dial.slot("button_1").matches("event.office_dial_button_1")
    assert not dial.slot("button_1").matches("event.office_dial_button_10")
    nuimo = model("senic_nuimo")
    assert nuimo.slot("control").matches("event.nuimo_control_button")


BASE = {
    "id": "x",
    "name": "X",
    "input": "event_entity",
    "picture": {"width": 10, "height": 10},
    "controls": [{"id": "a", "shape": "circle", "cx": 1, "cy": 1, "r": 1, "gestures": ["press"]}],
    "entities": [{"slot": "s", "find": "_a$", "events": {"short_release": {"control": "a", "raw": "tap"}}}],
}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"input": "zigbee"}, "input must be"),
        ({"controls": [{"id": "a", "shape": "star", "gestures": ["press"]}]}, "shape must be"),
        ({"controls": [{"id": "a", "shape": "circle", "cx": 1, "cy": 1, "r": 1, "gestures": ["wiggle"]}]}, "unknown gesture"),
        ({"entities": [{"slot": "s", "find": "(", "events": {}}]}, "valid pattern"),
        ({"entities": [{"slot": "s", "find": "x", "events": {"e": {"control": "zz", "raw": "tap"}}}]}, "no control"),
        ({"entities": [{"slot": "s", "find": "x", "events": {"e": {"control": "a", "raw": "tap", "gesture": "press"}}}]}, "exactly one"),
    ],
)
def test_bad_models_say_why(change, message):
    with pytest.raises(ModelError, match=message):
        parse_model({**BASE, **change})


def test_a_knx_model_needs_offsets():
    data = {**BASE, "input": "knx", "knx": {"tap": "tap"}}
    with pytest.raises(ModelError, match="knx' offset"):
        parse_model(data)


def test_a_zigbee2mqtt_model_picks_controls_from_a_field():
    data = {**BASE, "input": "zigbee2mqtt", "actions": {"flip": {"pick": "side", "controls": {1: "a"}, "gesture": "press"}}}
    data.pop("entities")
    m = parse_model(data)
    assert m.slots[0].events["flip"].controls == {"1": "a"}
    with pytest.raises(ModelError, match="no control 'zz'"):
        parse_model({**data, "actions": {"flip": {"pick": "side", "controls": {1: "zz"}, "gesture": "press"}}})
    with pytest.raises(ModelError, match="needs 'controls'"):
        parse_model({**data, "actions": {"flip": {"pick": "side", "gesture": "press"}}})
    with pytest.raises(ModelError, match="raw press"):
        parse_model({**data, "actions": {"flip": {"pick": "side", "controls": {1: "a"}, "raw": "tap"}}})
