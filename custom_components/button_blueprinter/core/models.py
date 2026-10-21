"""Switch models: what a kind of switch looks like and what its controls can do.

One YAML file per model in ``models/``. A model needs no code and no picture
file: the page draws it from the shapes here. Adding a model means adding one
file, unless it reaches Home Assistant in a new way (a new ``input``).

Inputs: ``knx`` (group addresses), ``event_entity`` (one or more event entities,
found by pattern) and ``zigbee2mqtt`` (the device's own Zigbee2MQTT messages,
for devices whose events carry more than an event entity shows, such as the
side a cube landed on or how far it turned: ``actions`` maps each ``action``
value, and ``pick`` chooses the control from a field of the same message).

No Home Assistant imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .gestures import GESTURES, RAW

INPUTS = ("knx", "event_entity", "zigbee2mqtt")
# A zigbee2mqtt model's actions, as one slot (the device's messages).
Z2M_SLOT = "zigbee2mqtt"
SHAPES = ("rect", "circle", "ring")
LOOKS = ("label", "icon")
# A model with a display (the D-Life Dynamics plate) has a look per state instead.
DISPLAY_LOOKS = ("label", "show", "icon_on", "icon_off", "colour_on", "colour_off")
DISPLAY_SHOW = ("icon", "icon_name", "none")
# What a telegram on each of a KNX plate's addresses means.
KNX_CHANNELS = ("tap", "hold")


class ModelError(ValueError):
    """A model file is wrong. The message says where."""


@dataclass(frozen=True)
class Control:
    id: str
    name: str
    shape: str
    geometry: dict[str, float]
    gestures: tuple[str, ...]
    knx: int | None = None  # offset from the switch's base addresses (KNX models)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "shape": self.shape,
            **self.geometry,
            "gestures": list(self.gestures),
            **({"knx": self.knx} if self.knx is not None else {}),
        }


@dataclass(frozen=True)
class EventMap:
    """What one of a device's own event types means."""

    control: str | None  # None when ``pick`` chooses it
    gesture: str | None = None  # a gesture straight away
    raw: str | None = None  # or a raw press for the timing engine (tap, down, up)
    turn: str | None = None  # or a dial turn: the signed attribute that says how far
    steps: str | None = None  # attribute holding the step count, for ``gesture``
    divide: float = 1.0  # device units per step
    pick: str | None = None  # or the control is chosen by this field's value...
    controls: dict[str, str] = field(default_factory=dict)  # ...value -> control

    def control_for(self, attributes: dict[str, Any]) -> str | None:
        if not self.pick:
            return self.control
        value = attributes.get(self.pick)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return self.controls.get(str(value)) if value is not None else None


@dataclass(frozen=True)
class Slot:
    """One event entity a switch of this model brings."""

    slot: str
    name: str
    find: str  # regular expression matched against the entity id
    events: dict[str, EventMap]

    def matches(self, entity_id: str) -> bool:
        return re.search(self.find, entity_id) is not None


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    maker: str
    input: str
    picture: dict[str, Any]
    controls: tuple[Control, ...]
    slots: tuple[Slot, ...] = ()
    knx: dict[str, str] = field(default_factory=dict)  # channel -> what it means
    looks: tuple[str, ...] = ()
    notes: str = ""
    icon_set: str | None = None  # icons must come from this set
    icon_only: tuple[str, ...] = ()  # ...and from this part of it, if given
    display: dict[str, Any] | None = None  # label_max, colours, show, defaults
    match: tuple[str, ...] = ()  # zigbee2mqtt: the device model ids this file is for

    def look_keys(self) -> tuple[str, ...]:
        return DISPLAY_LOOKS if self.display else LOOKS

    def control(self, control_id: str) -> Control | None:
        return next((c for c in self.controls if c.id == control_id), None)

    def slot(self, slot_id: str) -> Slot | None:
        return next((s for s in self.slots if s.slot == slot_id), None)

    def as_dict(self) -> dict[str, Any]:
        """What the page needs to draw and edit a switch of this model."""
        return {
            "id": self.id,
            "name": self.name,
            "maker": self.maker,
            "input": self.input,
            "picture": dict(self.picture),
            "controls": [c.as_dict() for c in self.controls],
            "slots": [{"slot": s.slot, "name": s.name, "find": s.find} for s in self.slots],
            "knx": dict(self.knx),
            "looks": list(self.look_keys() if self.display else self.looks),
            "notes": self.notes,
            "icon_set": self.icon_set,
            "icon_only": list(self.icon_only),
            "display": self.display,
            "match": list(self.match),
        }


def _need(data: dict, key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ModelError(f"{where}: '{key}' is missing")
    return data[key]


def _geometry(shape: str, raw: dict, where: str) -> dict[str, float]:
    keys = {"rect": ("x", "y", "w", "h"), "circle": ("cx", "cy", "r"), "ring": ("cx", "cy", "r", "inner")}[shape]
    try:
        return {k: float(_need(raw, k, where)) for k in keys}
    except (TypeError, ValueError) as err:
        raise ModelError(f"{where}: shape numbers must be numbers") from err


def _event_map(raw: Any, controls: dict[str, Control], where: str) -> EventMap:
    if not isinstance(raw, dict):
        raise ModelError(f"{where}: must be a mapping")
    pick = raw.get("pick")
    picked: dict[str, str] = {}
    control = None
    if pick:
        if not isinstance(raw.get("controls"), dict) or not raw["controls"]:
            raise ModelError(f"{where}: 'pick' needs 'controls' (value: control)")
        picked = {str(k): str(v) for k, v in raw["controls"].items()}
        for c in picked.values():
            if c not in controls:
                raise ModelError(f"{where}: no control '{c}'")
        if raw.get("raw"):
            raise ModelError(f"{where}: a picked control can't be a raw press")
    else:
        control = _need(raw, "control", where)
        if control not in controls:
            raise ModelError(f"{where}: no control '{control}'")
    kinds = [k for k in ("gesture", "raw", "turn") if raw.get(k)]
    if len(kinds) != 1:
        raise ModelError(f"{where}: give exactly one of gesture, raw or turn")
    gesture = raw.get("gesture")
    if gesture and gesture not in GESTURES:
        raise ModelError(f"{where}: unknown gesture '{gesture}'")
    if raw.get("raw") and raw["raw"] not in RAW:
        raise ModelError(f"{where}: raw must be one of {', '.join(sorted(RAW))}")
    try:
        divide = float(raw.get("divide", 1))
    except (TypeError, ValueError) as err:
        raise ModelError(f"{where}: divide must be a number") from err
    if divide <= 0:
        raise ModelError(f"{where}: divide must be above 0")
    return EventMap(
        control=control,
        gesture=gesture,
        raw=raw.get("raw"),
        turn=raw.get("turn"),
        steps=raw.get("steps"),
        divide=divide,
        pick=pick or None,
        controls=picked,
    )


def parse_model(data: Any, source: str = "model") -> Model:
    """A model from its YAML, checked. Raises ``ModelError``."""
    if not isinstance(data, dict):
        raise ModelError(f"{source}: must be a mapping")
    model_id = str(_need(data, "id", source))
    where = f"{source} ({model_id})"
    kind = _need(data, "input", where)
    if kind not in INPUTS:
        raise ModelError(f"{where}: input must be one of {', '.join(INPUTS)}")
    picture = _need(data, "picture", where)
    if not isinstance(picture, dict) or "width" not in picture or "height" not in picture:
        raise ModelError(f"{where}: picture needs width and height")

    controls: dict[str, Control] = {}
    for i, raw in enumerate(_need(data, "controls", where)):
        cw = f"{where} control {i + 1}"
        cid = str(_need(raw, "id", cw))
        if cid in controls:
            raise ModelError(f"{cw}: id '{cid}' used twice")
        shape = raw.get("shape", "rect")
        if shape not in SHAPES:
            raise ModelError(f"{cw}: shape must be one of {', '.join(SHAPES)}")
        gestures = tuple(_need(raw, "gestures", cw))
        for g in gestures:
            if g not in GESTURES:
                raise ModelError(f"{cw}: unknown gesture '{g}'")
        knx = raw.get("knx")
        if kind == "knx" and not isinstance(knx, int):
            raise ModelError(f"{cw}: a KNX model needs a whole-number 'knx' offset on each control")
        controls[cid] = Control(
            id=cid,
            name=str(raw.get("name", cid)),
            shape=shape,
            geometry=_geometry(shape, raw, cw),
            gestures=gestures,
            knx=knx if kind == "knx" else None,
        )

    slots: list[Slot] = []
    if kind == "event_entity":
        for i, raw in enumerate(_need(data, "entities", where)):
            sw = f"{where} entity {i + 1}"
            slot_id = str(_need(raw, "slot", sw))
            find = str(_need(raw, "find", sw))
            try:
                re.compile(find)
            except re.error as err:
                raise ModelError(f"{sw}: 'find' isn't a valid pattern ({err})") from err
            events = {
                str(name): _event_map(m, controls, f"{sw} event '{name}'")
                for name, m in (_need(raw, "events", sw) or {}).items()
            }
            slots.append(Slot(slot=slot_id, name=str(raw.get("name", slot_id)), find=find, events=events))
        if len({s.slot for s in slots}) != len(slots):
            raise ModelError(f"{where}: two entities share a slot name")
    if kind == "zigbee2mqtt":
        actions = _need(data, "actions", where)
        if not isinstance(actions, dict):
            raise ModelError(f"{where}: 'actions' must be a mapping")
        events = {str(name): _event_map(m, controls, f"{where} action '{name}'") for name, m in actions.items()}
        slots.append(Slot(slot=Z2M_SLOT, name="Zigbee2MQTT", find="", events=events))

    knx: dict[str, str] = {}
    if kind == "knx":
        knx = dict(_need(data, "knx", where))
        for channel, meaning in knx.items():
            if channel not in (*KNX_CHANNELS, "led"):
                raise ModelError(f"{where}: unknown KNX channel '{channel}'")
            if channel == "tap" and meaning != "tap":
                raise ModelError(f"{where}: the tap channel means 'tap'")
            if channel == "hold" and meaning not in GESTURES:
                raise ModelError(f"{where}: unknown gesture '{meaning}' for the hold channel")
        if "tap" not in knx:
            raise ModelError(f"{where}: a KNX model needs a tap channel")

    looks = tuple(data.get("looks", ()))
    for look in looks:
        if look not in LOOKS:
            raise ModelError(f"{where}: unknown look '{look}'")

    icon_set = None
    icon_only: tuple[str, ...] = ()
    if data.get("icons") is not None:
        icons = data["icons"]
        if not isinstance(icons, dict) or not icons.get("set"):
            raise ModelError(f"{where}: 'icons' needs a set")
        icon_set = str(icons["set"])
        icon_only = tuple(str(i) for i in icons.get("only", ()))
    display = None
    if data.get("display") is not None:
        raw = data["display"]
        if not isinstance(raw, dict):
            raise ModelError(f"{where}: 'display' must be a mapping")
        colours = list(raw.get("colours") or [])
        show = list(raw.get("show") or DISPLAY_SHOW)
        if not colours or not all(isinstance(c, str) for c in colours):
            raise ModelError(f"{where}: the display needs a list of colours")
        if set(show) - set(DISPLAY_SHOW):
            raise ModelError(f"{where}: display 'show' can only be {', '.join(DISPLAY_SHOW)}")
        try:
            label_max = int(raw.get("label_max", 12))
        except (TypeError, ValueError) as err:
            raise ModelError(f"{where}: label_max must be a number") from err
        defaults = dict(raw.get("defaults") or {})
        if set(defaults) - set(DISPLAY_LOOKS):
            raise ModelError(f"{where}: unknown display default")
        for key in ("colour_on", "colour_off"):
            if key in defaults and defaults[key] not in colours:
                raise ModelError(f"{where}: default {key} isn't one of the colours")
        if defaults.get("show", show[0]) not in show:
            raise ModelError(f"{where}: default 'show' isn't allowed")
        display = {"label_max": label_max, "colours": colours, "show": show, "defaults": defaults}
        if not icon_set:
            raise ModelError(f"{where}: a display needs an icon set")

    return Model(
        id=model_id,
        name=str(_need(data, "name", where)),
        maker=str(data.get("maker", "")),
        input=kind,
        picture=dict(picture),
        controls=tuple(controls.values()),
        slots=tuple(slots),
        knx=knx,
        looks=looks,
        notes=str(data.get("notes", "")).strip(),
        icon_set=icon_set,
        icon_only=icon_only,
        display=display,
        match=tuple(str(m) for m in data.get("match") or ()),
    )
