"""Looks someone wants but the switch can't take from Home Assistant.

A Schneider plate's icons, colours and names are set in ETS (the 8-button
display) or printed on an insert (the 4-button plate). Home Assistant can't
change them, so a wanted look is kept as a request until the plate matches:
after an ETS download and a fresh read of the ETS looks, or when an
administrator says it's done. No Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

from .icons import IconSet
from .models import Model

SHOW_ETS = {"icon": "Icon only", "icon_name": "Icon + name of the channel", "none": "No icon"}
ETS_SETTINGS = (
    ("show", "Indication type"),
    ("label", "Name of the channel"),
    ("icon_on", "Icon for status on"),
    ("icon_off", "Icon for status off"),
    ("colour_on", "Colour for status on"),
    ("colour_off", "Colour for status off"),
)


def changed_where(model: Model) -> str | None:
    """Where a look is really changed: 'ets' (display), 'insert' (printed), or None (only on this page)."""
    if model.display:
        return "ets"
    if model.icon_set:
        return "insert"
    return None


def full_look(model: Model, look: dict[str, str] | None) -> dict[str, str]:
    """A look with the model's defaults filled in and empty values dropped."""
    base = dict((model.display or {}).get("defaults") or {}) if model.display else {}
    base.update({k: v for k, v in (look or {}).items() if v not in (None, "")})
    return {k: base[k] for k in model.look_keys() if base.get(k) not in (None, "")}


def what_counts(model: Model, look: dict[str, str]) -> dict[str, str]:
    """The parts of a look the real switch shows (an insert's note is for this page only)."""
    if changed_where(model) == "insert":
        return {k: v for k, v in look.items() if k == "icon"}
    return look


def same_look(model: Model, a: dict[str, str] | None, b: dict[str, str] | None) -> bool:
    return what_counts(model, full_look(model, a)) == what_counts(model, full_look(model, b))


def _value(key: str, value: str | None, icon_set: IconSet | None) -> str:
    if value in (None, ""):
        return "(empty)" if key == "label" else "(none)"
    if key == "show":
        return SHOW_ETS.get(value, value)
    if key.startswith("icon"):
        icon = icon_set.icons.get(value) if icon_set else None
        return icon.name if icon else value
    if key.startswith("colour"):
        return value.capitalize()
    return value


def steps(
    model: Model, control: str, plate: dict[str, str] | None, wanted: dict[str, str], icon_set: IconSet | None
) -> dict[str, Any]:
    """What to change, in the words of the place it's changed (ETS settings or an insert)."""
    c = model.control(control)
    where = changed_where(model)
    now, want = full_look(model, plate), full_look(model, wanted)
    out: dict[str, Any] = {"where": where, "changes": []}
    if where == "ets":
        out["function"] = f"Function {(c.knx or 0) + 1}" if c else control
        for key, setting in ETS_SETTINGS:
            if now.get(key) != want.get(key):
                out["changes"].append(
                    {"setting": setting, "from": _value(key, now.get(key), icon_set), "to": _value(key, want.get(key), icon_set)}
                )
    elif where == "insert":
        if now.get("icon") != want.get("icon"):
            out["changes"].append(
                {"setting": "Insert", "from": _value("icon", now.get("icon"), icon_set), "to": _value("icon", want.get("icon"), icon_set)}
            )
    return out
