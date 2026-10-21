from __future__ import annotations

import pytest

from custom_components.button_blueprinter.core.icons import IconSetError, parse_icon_set

from .fixtures import icon_sets, model


def test_the_dlife_set_matches_the_ets_list():
    s = icon_sets()["schneider_dlife"]
    ets = sorted(i.ets for i in s.icons.values() if i.ets is not None)
    assert ets == list(range(1, 55))  # ETS app 1871 "Icon for status on/off": 1..54
    assert s.by_ets(33).id == "working" and s.by_ets(36).id == "gaming" and s.by_ets(1).id == "bulb_on"
    assert s.icons["message"].ets is None  # insert-only


def test_models_name_icons_that_exist():
    s = icon_sets()["schneider_dlife"]
    assert set(model("schneider_mtn6185").icon_only) <= set(s.icons)
    d = model("schneider_mtn619x").display
    assert d["label_max"] == 12 and "yellow" in d["colours"]
    assert d["defaults"]["icon_on"] in s.icons and d["defaults"]["icon_off"] in s.icons


def test_bad_sets():
    with pytest.raises(IconSetError):
        parse_icon_set({"id": "x", "icons": [{"id": "a", "name": "A", "mdi": "lightbulb"}]})
    with pytest.raises(IconSetError):
        parse_icon_set({"id": "x", "icons": [{"id": "a", "name": "A", "mdi": "mdi:a"}, {"id": "a", "name": "B", "mdi": "mdi:b"}]})
