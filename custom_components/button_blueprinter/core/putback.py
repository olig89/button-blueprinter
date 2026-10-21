"""Put back: presses that are for now, not for good.

A switch can say "put things back after N minutes", for all its controls or
only some (a play cube; a "task light" button on a wall plate). The first such
press saves how every light its binding touches looks; each press starts the
clock again; when it runs out, every light the switch still owns goes back to
how it was. A light someone else changes in the meantime (the wall, an app,
another button) is theirs again and is left alone.

This module has the rules: the setting, which entities a binding touches, what
a saved look is and how it is put back. No Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

RESTORABLE = ("light", "switch", "input_boolean", "fan")
MAX_MINUTES = 24 * 60
# Menu kinds whose ``entities`` are changed by the press.
CHANGES_ENTITIES = ("toggle", "turn_on", "turn_off", "brighter", "dimmer", "colour")
# A light's colour, by its colour mode: the attribute that holds it.
COLOUR_BY_MODE = {
    "xy": "xy_color",
    "hs": "hs_color",
    "rgb": "rgb_color",
    "rgbw": "rgbw_color",
    "rgbww": "rgbww_color",
    "color_temp": "color_temp_kelvin",
}


class PutBackError(ValueError):
    pass


def check(raw: Any, control_ids: list[str]) -> dict[str, Any] | None:
    """A clean copy of a switch's put-back setting, or None for "never"."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise PutBackError("Put back is a number of minutes")
    minutes = raw.get("minutes")
    if minutes in (None, "", 0):
        return None
    try:
        minutes = int(minutes)
    except (TypeError, ValueError) as err:
        raise PutBackError("Put back after a whole number of minutes") from err
    if not 1 <= minutes <= MAX_MINUTES:
        raise PutBackError(f"Put back after 1 to {MAX_MINUTES} minutes")
    out: dict[str, Any] = {"minutes": minutes}
    controls = raw.get("controls")
    if controls:
        if not isinstance(controls, list) or not all(isinstance(c, str) for c in controls):
            raise PutBackError("Put back: choose the buttons")
        unknown = [c for c in controls if c not in control_ids]
        if unknown:
            raise PutBackError(f"Put back: the model has no control '{unknown[0]}'")
        out["controls"] = list(dict.fromkeys(controls))
    return out


def applies(setting: dict[str, Any] | None, control: str) -> bool:
    return bool(setting) and (not setting.get("controls") or control in setting["controls"])


def touched(binding: dict[str, Any]) -> list[str]:
    """The entities a binding changes, as far as can be known: menu choices only.

    A scene comes back as the scene; whoever has Home Assistant expands it.
    Hand-written actions can do anything, so they touch nothing that can be put back.
    """
    menu = binding.get("menu") if isinstance(binding, dict) else None
    if not menu:
        return []
    if menu.get("kind") in CHANGES_ENTITIES:
        return list(menu.get("entities") or [])
    if menu.get("kind") == "scene":
        return [menu["scene"]]
    return []


def restorable(entity_id: str) -> bool:
    return entity_id.split(".", 1)[0] in RESTORABLE


def look(entity_id: str, state: str | None, attributes: dict[str, Any]) -> dict[str, Any] | None:
    """What gets saved and compared: on or off, and for a light that is on, brightness and colour.

    None when there is nothing to put back to (unavailable, unknown).
    """
    if state not in ("on", "off"):
        return None
    saved: dict[str, Any] = {"state": state}
    if state == "on" and entity_id.startswith("light."):
        if attributes.get("brightness") is not None:
            saved["brightness"] = attributes["brightness"]
        mode = attributes.get("color_mode")
        key = COLOUR_BY_MODE.get(mode)
        if key and attributes.get(key) is not None:
            value = attributes[key]
            saved[key] = list(value) if isinstance(value, (list, tuple)) else value
    return saved


def restore_actions(entity_id: str, saved: dict[str, Any]) -> list[dict]:
    domain = entity_id.split(".", 1)[0]
    if saved.get("state") == "off":
        return [{"action": f"{domain}.turn_off", "target": {"entity_id": entity_id}}]
    data = {k: v for k, v in saved.items() if k != "state"} if domain == "light" else {}
    action: dict[str, Any] = {"action": f"{domain}.turn_on", "target": {"entity_id": entity_id}}
    if data:
        action["data"] = data
    return [action]
