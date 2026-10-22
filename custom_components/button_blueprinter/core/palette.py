"""The menu of safe actions anyone in the household may give a button.

A binding is either a menu choice (``{"menu": {...}}``), which non-admins may set,
or free-form Home Assistant actions (``{"actions": [...]}``), which only admins may
set: an action runs with full rights, so free-form actions for everyone would let
anyone do anything an admin can.

This module checks menu choices, turns them into Home Assistant actions, and
recognises the simple action lists the old automations used, so imported
buttons stay editable from the menu. No Home Assistant imports.
"""

from __future__ import annotations

import re
from typing import Any

SWITCHABLE = ("light", "switch", "fan", "input_boolean", "cover", "media_player", "group")
MEDIA_COMMANDS = ("play_pause", "next", "previous", "volume_up", "volume_down", "mute")
VACUUM_MODES = ("vacuum", "vac_and_mop", "mop")
# Colours a light can be set to: the rainbow (no indigo) and back to plain white.
COLOURS: dict[str, dict[str, Any]] = {
    "red": {"rgb_color": [255, 0, 0]},
    "orange": {"rgb_color": [255, 110, 0]},
    "yellow": {"rgb_color": [255, 210, 0]},
    "green": {"rgb_color": [0, 255, 0]},
    "blue": {"rgb_color": [0, 0, 255]},
    "violet": {"rgb_color": [150, 0, 255]},
    "warm_white": {"color_temp_kelvin": 2700},
}

# Field types: ("entities", domains) a list, ("entity", domains) one, ("percent",),
# ("bool",), ("choice", values), ("area",) one Home Assistant area id, ("seconds",)
# an optional fade (left out: the light's own).
MAX_FADE = 10
MENU: dict[str, tuple[str, dict[str, tuple]]] = {
    "toggle": ("Switch on or off", {"entities": ("entities", SWITCHABLE)}),
    "turn_on": ("Switch on", {"entities": ("entities", SWITCHABLE), "brightness": ("percent",)}),
    "turn_off": ("Switch off", {"entities": ("entities", SWITCHABLE)}),
    "scene": ("Scene", {"scene": ("entity", ("scene",)), "again_off": ("bool",)}),
    "brighter": ("Brighter", {"entities": ("entities", ("light",)), "step": ("percent",), "fade": ("seconds",)}),
    "dimmer": ("Dimmer", {"entities": ("entities", ("light",)), "step": ("percent",), "fade": ("seconds",)}),
    "colour": ("Colour", {"entities": ("entities", ("light",)), "colour": ("choice", tuple(COLOURS)), "fade": ("seconds",)}),
    # For a switch that puts things back (putback.py): do it now.
    "put_back": ("Put things back now", {}),
    "media": ("Speaker", {"entity": ("entity", ("media_player",)), "command": ("choice", MEDIA_COMMANDS)}),
    "script": ("Run a script", {"script": ("entity", ("script",))}),
    "vacuum": (
        "Robot vacuum",
        {"vacuum": ("entity", ("vacuum",)), "area": ("area",), "mode": ("choice", VACUUM_MODES)},
    ),
}
DEFAULT_STEP = 10


class MenuError(ValueError):
    pass


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def check(choice: Any) -> dict[str, Any]:
    """A clean copy of a menu choice, or ``MenuError``."""
    if not isinstance(choice, dict) or choice.get("kind") not in MENU:
        raise MenuError("Choose what the button should do")
    kind = choice["kind"]
    _, fields = MENU[kind]
    unknown = set(choice) - set(fields) - {"kind"}
    if unknown:
        raise MenuError(f"Unknown setting: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {"kind": kind}
    for name, rule in fields.items():
        value = choice.get(name)
        kind_of = rule[0]
        if kind_of in ("entities", "entity"):
            ids = value if kind_of == "entities" else [value]
            if not isinstance(ids, list) or not ids or not all(isinstance(e, str) and "." in e for e in ids):
                raise MenuError("Choose what to control")
            bad = [e for e in ids if _domain(e) not in rule[1]]
            if bad:
                raise MenuError(f"{bad[0]} can't be used for this")
            out[name] = list(dict.fromkeys(ids)) if kind_of == "entities" else ids[0]
        elif kind_of == "choice":
            if value not in rule[1]:
                raise MenuError("Choose one of the options")
            out[name] = value
        elif kind_of == "percent":
            if value is None or value == "":
                continue
            try:
                pct = float(value)
            except (TypeError, ValueError) as err:
                raise MenuError("Use a number from 1 to 100") from err
            if not 1 <= pct <= 100:
                raise MenuError("Use a number from 1 to 100")
            out[name] = int(pct) if pct == int(pct) else pct
        elif kind_of == "seconds":
            if value is None or value == "":
                continue
            try:
                secs = float(value)
            except (TypeError, ValueError) as err:
                raise MenuError(f"Use a number of seconds from 0 to {MAX_FADE}") from err
            if not 0 <= secs <= MAX_FADE:
                raise MenuError(f"Use a number of seconds from 0 to {MAX_FADE}")
            out[name] = int(secs) if secs == int(secs) else round(secs, 2)
        elif kind_of == "bool":
            out[name] = bool(value)
        elif kind_of == "area":
            if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]+", value):
                raise MenuError("Choose an area")
            out[name] = value
    return out


def _toggle(entities: list[str]) -> list[dict]:
    domains = {_domain(e) for e in entities}
    if len(entities) == 1 and domains <= {"light", "switch", "fan", "input_boolean", "media_player", "cover"}:
        return [{"action": f"{_domain(entities[0])}.toggle", "target": {"entity_id": entities[0]}}]
    # Several: any on -> all off, else all on (a group behaves as one).
    return [
        {
            "if": [{"condition": "state", "entity_id": list(entities), "state": "on", "match": "any"}],
            "then": [{"action": "homeassistant.turn_off", "target": {"entity_id": list(entities)}}],
            "else": [{"action": "homeassistant.turn_on", "target": {"entity_id": list(entities)}}],
        }
    ]


def _fade(choice: dict[str, Any]) -> dict[str, Any]:
    """A chosen fade as the light's transition; none chosen: the light's own."""
    return {"transition": choice["fade"]} if "fade" in choice else {}


def to_actions(choice: dict[str, Any]) -> list[dict]:
    """The Home Assistant actions a (checked) menu choice runs.

    Two run variables are used: ``steps`` (how far a dial turned, 1 otherwise)
    and ``switch_scenes`` (the scenes this switch's buttons turn on, for "again
    turns it off").
    """
    kind = choice["kind"]
    if kind == "toggle":
        return _toggle(choice["entities"])
    if kind == "turn_on":
        ents = choice["entities"]
        if "brightness" in choice and all(_domain(e) == "light" for e in ents):
            return [{"action": "light.turn_on", "target": {"entity_id": ents}, "data": {"brightness_pct": choice["brightness"]}}]
        return [{"action": "homeassistant.turn_on", "target": {"entity_id": ents}}]
    if kind == "turn_off":
        return [{"action": "homeassistant.turn_off", "target": {"entity_id": choice["entities"]}}]
    if kind in ("brighter", "dimmer"):
        sign = "" if kind == "brighter" else "-"
        step = choice.get("step", DEFAULT_STEP)
        return [
            {
                "action": "light.turn_on",
                "target": {"entity_id": choice["entities"]},
                "data": {"brightness_step_pct": f"{{{{ {sign}{step} * (steps | int(1)) }}}}", **_fade(choice)},
            }
        ]
    if kind == "put_back":
        return [{"action": "button_blueprinter.put_back", "data": {"switch": "{{ switch }}"}}]
    if kind == "colour":
        # Keeps the brightness; a light that is off comes on at its last brightness.
        return [{"action": "light.turn_on", "target": {"entity_id": choice["entities"]}, "data": {**COLOURS[choice["colour"]], **_fade(choice)}}]
    if kind == "scene":
        scene = choice["scene"]
        on = [{"action": "scene.turn_on", "target": {"entity_id": scene}}]
        if not choice.get("again_off"):
            return on
        # Same as the office's old automation: if this scene is the one of this
        # switch's scenes used last, and any of its lights is still on, switch its
        # lights off instead.
        lights = f"{{{{ state_attr('{scene}', 'entity_id') | default([], true) | list }}}}"
        last = (
            "{{ expand(switch_scenes | default([])) | rejectattr('state', 'in', ['unknown', 'unavailable'])"
            " | sort(attribute='state') | map(attribute='entity_id') | list | last | default('') }}"
        )
        return [
            {"variables": {"scene_lights": lights, "last_scene": last}},
            {
                "if": [
                    {"condition": "template", "value_template": f"{{{{ last_scene == '{scene}' }}}}"},
                    {
                        "condition": "template",
                        "value_template": "{{ scene_lights | select('is_state', 'on') | list | count > 0 }}",
                    },
                ],
                "then": [{"action": "homeassistant.turn_off", "target": {"entity_id": "{{ scene_lights }}"}}],
                "else": on,
            },
        ]
    if kind == "media":
        target = {"entity_id": choice["entity"]}
        command = choice["command"]
        if command in ("volume_up", "volume_down"):
            return [
                {
                    "repeat": {
                        "count": "{{ steps | int(1) }}",
                        "sequence": [{"action": f"media_player.{command}", "target": target}],
                    }
                }
            ]
        if command == "mute":
            return [
                {
                    "action": "media_player.volume_mute",
                    "target": target,
                    "data": {"is_volume_muted": f"{{{{ not state_attr('{choice['entity']}', 'is_volume_muted') }}}}"},
                }
            ]
        name = {"play_pause": "media_play_pause", "next": "media_next_track", "previous": "media_previous_track"}[command]
        return [{"action": f"media_player.{name}", "target": target}]
    if kind == "script":
        return [{"action": "script.turn_on", "target": {"entity_id": choice["script"]}}]
    if kind == "vacuum":
        vac = choice["vacuum"]
        # Roborock's cleaning mode is a robot-wide select named after the vacuum and
        # has to be set before the clean starts. A robot without one skips it.
        mode_select = f"select.{vac.split('.', 1)[1]}_cleaning_mode"
        has_mode = f"{{{{ '{choice['mode']}' in (state_attr('{mode_select}', 'options') or []) }}}}"
        return [
            {
                # A press while it is out cleaning sends it home: a wrong press is undone by another.
                "if": [{"condition": "state", "entity_id": vac, "state": "cleaning"}],
                "then": [{"action": "vacuum.return_to_base", "target": {"entity_id": vac}}],
                "else": [
                    {
                        "if": [{"condition": "template", "value_template": has_mode}],
                        "then": [
                            {"action": "select.select_option", "target": {"entity_id": mode_select}, "data": {"option": choice["mode"]}}
                        ],
                    },
                    {"action": "vacuum.clean_area", "target": {"entity_id": vac}, "data": {"cleaning_area_id": [choice["area"]]}},
                ],
            }
        ]
    raise MenuError(f"unknown menu kind {kind}")


def scenes_of(bindings: dict[str, dict[str, dict]]) -> list[str]:
    """Every scene a switch's menu bindings turn on."""
    found = []
    for gestures in bindings.values():
        for binding in gestures.values():
            menu = binding.get("menu") if isinstance(binding, dict) else None
            if menu and menu.get("kind") == "scene" and menu.get("scene") not in found:
                found.append(menu["scene"])
    return found


# ---- recognising simple actions (for imported automations) -------------------------


def _ids(target: Any) -> list[str] | None:
    if not isinstance(target, dict) or set(target) != {"entity_id"}:
        return None
    ids = target["entity_id"]
    ids = [ids] if isinstance(ids, str) else ids
    return list(ids) if isinstance(ids, list) and all(isinstance(i, str) and "{" not in i for i in ids) else None


def from_actions(actions: list) -> dict[str, Any] | None:
    """The menu choice an action list amounts to, or None if it isn't one."""
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
        return None
    a = actions[0]
    name = a.get("action", a.get("service"))
    if isinstance(name, str):
        ids = _ids(a.get("target"))
        data = a.get("data") or {}
        if not ids:
            return None
        domain, _, service = name.partition(".")
        if service == "toggle" and not data and len(ids) == 1 and domain == _domain(ids[0]):
            return {"kind": "toggle", "entities": ids}
        if service == "turn_on" and domain in ("light", "homeassistant", *SWITCHABLE):
            if not data:
                return {"kind": "turn_on", "entities": ids}
            if set(data) == {"brightness_pct"} and domain == "light" and isinstance(data["brightness_pct"], (int, float)):
                return {"kind": "turn_on", "entities": ids, "brightness": data["brightness_pct"]}
        if service == "turn_off" and not data:
            return {"kind": "turn_off", "entities": ids}
        if domain == "scene" and service == "turn_on" and len(ids) == 1 and not data:
            return {"kind": "scene", "scene": ids[0], "again_off": False}
        return None
    # The old "any on -> all off, else all on" toggle.
    cond = a.get("if")
    if isinstance(cond, list) and len(cond) == 1 and set(a) == {"if", "then", "else"}:
        c = cond[0]
        ids = c.get("entity_id") if isinstance(c, dict) else None
        ids = [ids] if isinstance(ids, str) else ids
        if (
            isinstance(c, dict)
            and c.get("condition") == "state"
            and c.get("state") == "on"
            and c.get("match", "all") == "any"
            and isinstance(ids, list)
        ):
            then, other = a["then"], a["else"]
            if (
                len(then) == 1
                and len(other) == 1
                and str(then[0].get("action", "")).endswith(".turn_off")
                and str(other[0].get("action", "")).endswith(".turn_on")
                and sorted(_ids(then[0].get("target")) or []) == sorted(ids)
                and sorted(_ids(other[0].get("target")) or []) == sorted(ids)
                and not then[0].get("data")
                and not other[0].get("data")
            ):
                return {"kind": "toggle", "entities": list(ids)}
    return None
