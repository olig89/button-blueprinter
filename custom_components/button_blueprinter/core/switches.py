"""A switch in a room: its model, inputs, looks, wanted looks, fixed controls, bindings and LEDs.

Stored as plain dicts (``as_dict`` / ``from_dict``). No Home Assistant imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import knx as knx_addr
from .icons import IconSet
from .models import Model
from .palette import MenuError, check as check_menu
from .putback import PutBackError, check as check_put_back
from .requests import changed_where

MODES = ("live", "dry_run", "off")
MODE_LABEL = {"live": "On", "dry_run": "Dry run", "off": "Off"}
ICON = re.compile(r"^mdi:[a-z0-9-]+$")


class SwitchError(ValueError):
    pass


@dataclass
class Switch:
    id: str
    name: str
    model: str
    area_id: str | None = None
    mode: str = "dry_run"  # a new switch only logs until someone says otherwise
    knx: dict[str, str] = field(default_factory=dict)  # KNX models: tap/hold/led bases, address
    entities: dict[str, str] = field(default_factory=dict)  # event-entity models: slot -> entity
    device: str | None = None  # zigbee2mqtt models: the Home Assistant device id
    looks: dict[str, dict[str, str]] = field(default_factory=dict)  # control -> how it looks now (on the plate)
    # control -> {"look": {...}, "by": name, "at": iso time}: a look someone asked for that
    # only ETS or a new insert can give (Schneider plates). Cleared once the plate matches.
    wanted: dict[str, dict[str, Any]] = field(default_factory=dict)
    fixed: dict[str, dict[str, str]] = field(default_factory=dict)  # control -> gesture -> what does it
    bindings: dict[str, dict[str, dict]] = field(default_factory=dict)  # control -> gesture -> binding
    leds: dict[str, dict[str, str]] = field(default_factory=dict)  # control -> {entity_id, state}
    put_back: dict[str, Any] | None = None  # {"minutes": n, "controls": [...]}: presses are for now (putback.py)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "area_id": self.area_id,
            "mode": self.mode,
            "knx": dict(self.knx),
            "entities": dict(self.entities),
            "device": self.device,
            "looks": {c: dict(v) for c, v in self.looks.items()},
            "wanted": {c: {**v, "look": dict(v.get("look") or {})} for c, v in self.wanted.items()},
            "fixed": {c: dict(v) for c, v in self.fixed.items()},
            "bindings": {c: {g: dict(b) for g, b in v.items()} for c, v in self.bindings.items()},
            "leds": {c: dict(v) for c, v in self.leds.items()},
            "put_back": dict(self.put_back) if self.put_back else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Switch:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            model=str(data["model"]),
            area_id=data.get("area_id") or None,
            mode=data.get("mode") if data.get("mode") in MODES else "dry_run",
            knx=dict(data.get("knx") or {}),
            entities=dict(data.get("entities") or {}),
            device=str(data["device"]) if data.get("device") else None,
            looks={c: dict(v) for c, v in (data.get("looks") or {}).items()},
            wanted={c: {**v, "look": dict(v.get("look") or {})} for c, v in (data.get("wanted") or {}).items() if isinstance(v, dict)},
            fixed={c: dict(v) for c, v in (data.get("fixed") or {}).items()},
            bindings={c: {g: dict(b) for g, b in v.items()} for c, v in (data.get("bindings") or {}).items()},
            leds={c: dict(v) for c, v in (data.get("leds") or {}).items()},
            put_back=dict(data["put_back"]) if isinstance(data.get("put_back"), dict) else None,
        )

    def binding(self, control: str, gesture: str) -> dict | None:
        return self.bindings.get(control, {}).get(gesture)

    def is_fixed(self, control: str, gesture: str) -> bool:
        return gesture in self.fixed.get(control, {})

    def wants_double(self, control: str) -> bool:
        return self.binding(control, "double_press") is not None


def check_binding(binding: Any) -> dict:
    """A clean copy of one binding: a menu choice or a list of actions."""
    if not isinstance(binding, dict) or len(binding) != 1 or not ({"menu", "actions"} & set(binding)):
        raise SwitchError("A binding is either a menu choice or a list of actions")
    if "menu" in binding:
        try:
            return {"menu": check_menu(binding["menu"])}
        except MenuError as err:
            raise SwitchError(str(err)) from err
    actions = binding["actions"]
    if not isinstance(actions, list) or not actions or not all(isinstance(a, dict) for a in actions):
        raise SwitchError("Actions must be a list of actions")
    return {"actions": actions}


def check(switch: Switch, model: Model, icon_sets: dict[str, IconSet] | None = None) -> None:
    """Raise ``SwitchError`` if the switch doesn't fit its model. Bindings are checked too.

    ``icon_sets`` must be given when the model uses one; otherwise its icons can't be checked.
    """
    if not switch.name.strip():
        raise SwitchError("Give the switch a name")
    if switch.mode not in MODES:
        raise SwitchError("Unknown mode")
    if model.input == "knx":
        try:
            knx_addr.check(model, switch.knx)
        except knx_addr.AddressError as err:
            raise SwitchError(str(err)) from err
    elif model.input == "zigbee2mqtt":
        if switch.entities:
            raise SwitchError("This switch is a Zigbee2MQTT device, not event entities")
    else:
        unknown = set(switch.entities) - {s.slot for s in model.slots}
        if unknown:
            raise SwitchError(f"The model has no entity slot '{sorted(unknown)[0]}'")
        for slot, entity_id in switch.entities.items():
            if not str(entity_id).startswith("event."):
                raise SwitchError(f"{slot}: choose an event entity")
    for part, what in (("looks", switch.looks), ("wanted", switch.wanted), ("fixed", switch.fixed), ("bindings", switch.bindings), ("leds", switch.leds)):
        for control in what:
            if model.control(control) is None:
                raise SwitchError(f"{part}: the model has no control '{control}'")
    try:
        switch.put_back = check_put_back(switch.put_back, [c.id for c in model.controls])
    except PutBackError as err:
        raise SwitchError(str(err)) from err
    check_looks(switch.looks, model, icon_sets)
    if switch.wanted:
        if changed_where(model) is None:
            raise SwitchError("This switch's looks are set here directly, not asked for")
        for control, request in switch.wanted.items():
            if not isinstance(request, dict) or not isinstance(request.get("look"), dict):
                raise SwitchError("A wanted look needs a look")
            if "in_ets" in request and not isinstance(request["in_ets"], dict):
                raise SwitchError("“In ETS” is who marked it and when")
        check_looks({c: r["look"] for c, r in switch.wanted.items()}, model, icon_sets)
    for control, gestures in {**switch.fixed, **switch.bindings}.items():
        allowed = set(model.control(control).gestures)
        for gesture in gestures:
            if gesture not in allowed:
                raise SwitchError(f"{model.control(control).name} can't do '{gesture}'")
    for control, gestures in switch.fixed.items():
        for gesture, text in gestures.items():
            if not str(text).strip():
                raise SwitchError("Say what a fixed button does")
            if switch.binding(control, gesture):
                raise SwitchError(f"{model.control(control).name}: a fixed gesture can't have a binding too")
    for control, gestures in switch.bindings.items():
        for gesture, binding in list(gestures.items()):
            gestures[gesture] = check_binding(binding)
            if (gestures[gesture].get("menu") or {}).get("kind") == "put_back" and not switch.put_back:
                raise SwitchError("Turn on putting lights back for this switch first")
    if switch.leds:
        if model.input != "knx" or "led" not in model.knx:
            raise SwitchError("This model has no LEDs")
        if not switch.knx.get("led"):
            raise SwitchError("Set the LED base address first")
        for control, rule in switch.leds.items():
            if not str(rule.get("entity_id", "")).count("."):
                raise SwitchError("An LED follows an entity")
            if set(rule) - {"entity_id", "state"}:
                raise SwitchError("An LED rule is an entity and a state")


def check_looks(looks: dict[str, dict[str, str]], model: Model, icon_sets: dict[str, IconSet] | None) -> None:
    """Looks must be what the real switch can show: its icons, its colours, its label length."""
    keys = model.look_keys()
    icon_keys = ("icon_on", "icon_off") if model.display else ("icon",)
    icon_set = (icon_sets or {}).get(model.icon_set) if model.icon_set else None
    for control, look in looks.items():
        if not isinstance(look, dict) or set(look) - set(keys):
            raise SwitchError(f"A look here is: {', '.join(keys)}")
        for key in icon_keys:
            value = look.get(key)
            if not value:
                continue
            if model.icon_set and icon_set is None:
                raise SwitchError(f"The icon set '{model.icon_set}' isn't loaded")
            if icon_set is None:
                if not ICON.match(value):
                    raise SwitchError(f"'{value}' isn't an icon name like mdi:lightbulb")
                continue
            icon = icon_set.icons.get(value)
            if icon is None or (model.icon_only and value not in model.icon_only):
                raise SwitchError(f"'{value}' isn't one of this switch's icons")
            if model.display and icon.ets is None:
                raise SwitchError(f"{icon.name} can't be shown on this display")
        if model.display:
            d = model.display
            if len(look.get("label", "")) > d["label_max"]:
                raise SwitchError(f"The display fits {d['label_max']} characters")
            for key in ("colour_on", "colour_off"):
                if look.get(key) and look[key] not in d["colours"]:
                    raise SwitchError(f"The display's colours are {', '.join(d['colours'])}")
            if look.get("show") and look["show"] not in d["show"]:
                raise SwitchError("Show is icon, icon_name or none")


def new_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_") or "switch"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def led_value(rule: dict[str, str], state: str | None) -> int:
    """1 if the LED should be lit for this state of its entity."""
    return 1 if state is not None and state == rule.get("state", "on") else 0
