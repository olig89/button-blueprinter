"""Shared bits for the core tests: the shipped models, and two automations in
the shape real wall-button automations have."""

from __future__ import annotations

from pathlib import Path

import yaml

from custom_components.button_blueprinter.core.icons import IconSet, parse_icon_set
from custom_components.button_blueprinter.core.models import Model, parse_model

MODELS_DIR = Path(__file__).parents[2] / "custom_components" / "button_blueprinter" / "models"
ICON_SETS_DIR = MODELS_DIR.parent / "icon_sets"


def icon_sets() -> dict[str, IconSet]:
    sets = [parse_icon_set(yaml.safe_load(f.read_text(encoding="utf-8")), f.name) for f in ICON_SETS_DIR.glob("*.yaml")]
    return {s.id: s for s in sets}


def model(model_id: str) -> Model:
    return parse_model(yaml.safe_load((MODELS_DIR / f"{model_id}.yaml").read_text(encoding="utf-8")), model_id)


def _tap(ga, tid):
    return {"trigger": "event", "event_type": "knx_event", "event_data": {"destination": ga}, "id": tid}


def _opt(tid, seq):
    return {"conditions": [{"condition": "trigger", "id": tid}], "sequence": seq}


SMALL_BATHROOM = {
    "id": "1000000000001",
    "alias": "Wall buttons: Small Bathroom (1.1.31)",
    "triggers": [
        _tap("6/0/40", "b1_tap"),
        _tap("6/1/40", "b1_hold"),
        _tap("6/0/41", "b2_tap"),
        _tap("6/0/42", "b3_tap"),
        _tap("6/1/42", "b3_hold"),
        _tap("6/0/43", "b4_tap"),
    ],
    "actions": [
        {
            "choose": [
                _opt("b1_tap", [{"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_ceiling"}}]),
                _opt(
                    "b1_hold",
                    [{"action": "light.turn_on", "target": {"entity_id": ["light.small_bathroom_ceiling"]}, "data": {"brightness_pct": 100}}],
                ),
                _opt("b2_tap", [{"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_ceiling"}}]),
                _opt("b3_tap", [{"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_mirror"}}]),
                _opt(
                    "b3_hold",
                    [{"action": "light.turn_on", "target": {"entity_id": ["light.small_bathroom_mirror"]}, "data": {"brightness_pct": 100}}],
                ),
                _opt("b4_tap", [{"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_mirror"}}]),
            ]
        }
    ],
    "mode": "queued",
    "max": 10,
}

STAIRS_LAMPS = ["light.hall_pendant_left", "light.hall_pendant_middle", "light.hall_pendant_right"]
ANY_ON_TOGGLE = {
    "if": [{"condition": "state", "entity_id": STAIRS_LAMPS, "state": "on", "match": "any"}],
    "then": [{"action": "light.turn_off", "target": {"entity_id": STAIRS_LAMPS}}],
    "else": [{"action": "light.turn_on", "target": {"entity_id": STAIRS_LAMPS}}],
}

OFFICE = {
    "id": "1000000000002",
    "alias": "Wall buttons: Office (1.1.32)",
    "triggers": [_tap("6/0/60", "b1"), _tap("6/0/62", "b3"), _tap("6/0/64", "b5")],
    "actions": [
        {
            "if": [{"condition": "template", "value_template": "{{ last_used == pressed }}"}],
            "then": [{"action": "light.turn_off", "target": {"entity_id": ["light.office_lamp"]}}],
            "else": [{"action": "scene.turn_on", "target": {"entity_id": "{{ pressed }}"}}],
        }
    ],
}
