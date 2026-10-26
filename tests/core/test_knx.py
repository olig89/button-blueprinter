from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core import knx
from custom_components.button_blueprinter.core.palette import from_actions

from .fixtures import ANY_ON_TOGGLE, OFFICE, SMALL_BATHROOM, model

SMALL = {"tap": "6/0/40", "hold": "6/1/40", "led": "6/2/40", "address": "1.1.31"}


def test_addresses_follow_the_offsets():
    four = model("schneider_mtn6185")
    got = knx.addresses(four, SMALL)
    assert got["6/0/40"] == ("b1", "tap")
    assert got["6/0/41"] == ("b2", "tap")
    assert got["6/1/43"] == ("b4", "hold")
    assert knx.led_addresses(four, SMALL)["b3"] == "6/2/42"


@pytest.mark.parametrize("bad", ["6/0", "6/8/1", "32/0/1", "6/0/256", "x"])
def test_bad_addresses(bad):
    with pytest.raises(knx.AddressError):
        knx.parse(bad)


def test_offset_past_the_end():
    with pytest.raises(knx.AddressError):
        knx.offset("6/0/254", 3)


def test_reads_the_small_bathroom_automation():
    bindings, notes = knx.read_automation(model("schneider_mtn6185"), SMALL, SMALL_BATHROOM)
    assert notes == []
    assert set(bindings) == {"b1", "b2", "b3", "b4"}
    assert set(bindings["b1"]) == {"press", "long_press"}
    assert set(bindings["b2"]) == {"press"}  # its hold is the room fallback on the bus
    assert from_actions(bindings["b1"]["press"]) == {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}
    assert from_actions(bindings["b3"]["long_press"]) == {
        "kind": "turn_on",
        "entities": ["light.small_bathroom_mirror"],
        "brightness": 100,
    }


def test_the_office_automation_is_not_simple_and_says_so():
    office = {"tap": "6/0/60", "hold": "6/1/60", "led": "6/2/60"}
    bindings, notes = knx.read_automation(model("schneider_mtn619x"), office, OFFICE)
    assert bindings == {}
    assert any("choose" in n for n in notes)


def test_any_on_toggle_is_recognised():
    got = from_actions([ANY_ON_TOGGLE])
    assert got["kind"] == "toggle" and len(got["entities"]) == 3
