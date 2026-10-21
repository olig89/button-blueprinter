"""KNX group addresses for a plate, and reading the old wall-button automations.

A KNX plate's switch stores a base address per channel (``tap``, ``hold``,
``led``), e.g. ``6/0/40``. A control's address is the base plus the control's
offset in the model. No Home Assistant imports.
"""

from __future__ import annotations

import re
from typing import Any

from .models import Model

_GA_ANY = re.compile(r"^(\d{1,2})/(\d)/(\d{1,3})$")


class AddressError(ValueError):
    pass


def parse(address: str) -> tuple[int, int, int]:
    m = _GA_ANY.match(str(address).strip())
    if not m:
        raise AddressError(f"'{address}' isn't a three-level group address like 6/0/8")
    main, middle, sub = (int(x) for x in m.groups())
    if main > 31 or middle > 7 or sub > 255:
        raise AddressError(f"'{address}' is out of range")
    return main, middle, sub


def offset(base: str, by: int) -> str:
    main, middle, sub = parse(base)
    if not 0 <= sub + by <= 255:
        raise AddressError(f"{base} + {by} is past the end of its middle group")
    return f"{main}/{middle}/{sub + by}"


def addresses(model: Model, knx: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Every input address of a switch -> (control, channel). Channels without a base are skipped."""
    out: dict[str, tuple[str, str]] = {}
    for channel in ("tap", "hold"):
        base = knx.get(channel)
        if not base or channel not in model.knx:
            continue
        for control in model.controls:
            out[offset(base, control.knx or 0)] = (control.id, channel)
    return out


def led_addresses(model: Model, knx: dict[str, str]) -> dict[str, str]:
    """Control -> its LED address, if the model has LEDs and the switch has a base."""
    base = knx.get("led")
    if not base or "led" not in model.knx:
        return {}
    return {c.id: offset(base, c.knx or 0) for c in model.controls}


def check(model: Model, knx: dict[str, str]) -> None:
    """Raise ``AddressError`` if the switch's bases are missing or wrong."""
    if not knx.get("tap"):
        raise AddressError("The tap address is needed")
    for channel in ("tap", "hold", "led"):
        if knx.get(channel):
            parse(knx[channel])
    addresses(model, knx)
    led_addresses(model, knx)


# ---- reading an old "Wall buttons" automation -------------------------------------


def _destination(trigger: dict) -> str | None:
    if trigger.get("trigger", trigger.get("platform")) == "event" and trigger.get("event_type") == "knx_event":
        return (trigger.get("event_data") or {}).get("destination")
    if trigger.get("trigger", trigger.get("platform")) == "knx.telegram":
        dest = trigger.get("destination")
        if isinstance(dest, list) and len(dest) == 1:
            return dest[0]
        return dest if isinstance(dest, str) else None
    return None


def read_automation(model: Model, knx: dict[str, str], config: dict[str, Any]) -> tuple[dict, list[str]]:
    """Bindings from a "choose by trigger id" automation, and notes on what couldn't be read.

    Returns ``({control: {gesture: [actions]}}, notes)``. Only the simple shape is
    read: one trigger per address, each with an id, and a ``choose`` whose options
    each test one trigger id. Anything else is left out and named in the notes.
    """
    by_address = addresses(model, knx)
    gesture_of = {"tap": "press", "hold": model.knx.get("hold", "long_press")}
    trigger_ids: dict[str, tuple[str, str]] = {}
    notes: list[str] = []
    for trig in config.get("triggers", config.get("trigger", [])) or []:
        dest = _destination(trig)
        tid = trig.get("id")
        if not dest or not tid:
            notes.append(f"Skipped a trigger that isn't a single KNX address with an id: {trig}")
            continue
        if dest not in by_address:
            notes.append(f"{dest} isn't one of this switch's addresses")
            continue
        control, channel = by_address[dest]
        trigger_ids[str(tid)] = (control, gesture_of[channel])

    actions = config.get("actions", config.get("action", [])) or []
    if isinstance(actions, dict):
        actions = [actions]
    bindings: dict[str, dict[str, list]] = {}
    chooses = [a for a in actions if isinstance(a, dict) and "choose" in a]
    if len(chooses) != 1 or len(actions) != 1:
        notes.append("The actions aren't a single 'choose' by trigger id, so nothing was read")
        return bindings, notes
    for option in chooses[0]["choose"]:
        conds = option.get("conditions", [])
        if isinstance(conds, dict):
            conds = [conds]
        ids = [c.get("id") for c in conds if isinstance(c, dict) and c.get("condition") == "trigger"]
        if len(conds) != 1 or len(ids) != 1:
            notes.append("Skipped an option that tests more than one trigger id")
            continue
        tid = ids[0][0] if isinstance(ids[0], list) and len(ids[0]) == 1 else ids[0]
        if tid not in trigger_ids:
            notes.append(f"Skipped option for unknown trigger id {tid}")
            continue
        control, gesture = trigger_ids[tid]
        seq = option.get("sequence", [])
        bindings.setdefault(control, {})[gesture] = seq if isinstance(seq, list) else [seq]
    if chooses[0].get("default"):
        notes.append("The 'default' branch was not read")
    return bindings, notes
