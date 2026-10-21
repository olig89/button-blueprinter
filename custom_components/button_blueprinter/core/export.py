"""A switch's bindings as one plain Home Assistant automation: the way out.

What can't be written as a plain trigger is left out and listed in the
description: a double tap Button Blueprinter times itself, and holds made from
raw down / up events. No Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

from . import knx as knx_addr
from .gestures import label
from .models import Model
from .palette import scenes_of, to_actions
from .switches import Switch


def _actions(binding: dict) -> list[dict]:
    return to_actions(binding["menu"]) if "menu" in binding else list(binding["actions"])


def to_automation(switch: Switch, model: Model, topic: str | None = None) -> dict[str, Any]:
    """``topic`` is a zigbee2mqtt switch's device topic (it comes from Home Assistant's device)."""
    triggers: list[dict] = []
    options: list[dict] = []
    left_out: list[str] = []

    def add(trigger: dict, control: str, gesture: str, steps: str | None = None) -> None:
        binding = switch.binding(control, gesture)
        if binding is None:
            return
        tid = f"{control}__{gesture}"
        triggers.append({**trigger, "id": tid})
        seq = _actions(binding)
        if steps:
            seq = [{"variables": {"steps": steps}}, *seq]
        options.append({"conditions": [{"condition": "trigger", "id": tid}], "sequence": seq})

    if model.input == "knx":
        for address, (control, channel) in knx_addr.addresses(model, switch.knx).items():
            gesture = "press" if channel == "tap" else model.knx[channel]
            trig = {
                "trigger": "knx.telegram",
                "destination": [address],
                "group_value_read": False,
                "group_value_response": False,
                "outgoing": False,
            }
            add(trig, control, gesture)
    elif model.input == "zigbee2mqtt":
        for action, m in (model.slots[0].events.items() if topic else ()):
            trig = {"trigger": "mqtt", "topic": topic, "value_template": "{{ value_json.action | default('') }}", "payload": action}
            pairs = m.controls.items() if m.pick else [(None, m.control)]
            for value, control in pairs:
                gesture = m.gesture or "press"
                binding = switch.binding(control, gesture)
                if binding is None:
                    continue
                tid = f"{control}__{gesture}"
                conditions: list[dict] = [{"condition": "trigger", "id": tid}]
                if value is not None:
                    conditions.append(
                        {"condition": "template", "value_template": f"{{{{ trigger.payload_json.{m.pick} | string == '{value}' }}}}"}
                    )
                seq = _actions(binding)
                if m.steps:
                    steps = f"{{{{ (trigger.payload_json.{m.steps} | float(1) | abs / {m.divide}) | round | int | max(1) }}}}"
                    seq = [{"variables": {"steps": steps}}, *seq]
                # Several actions can mean the same gesture (a flip, a side up): they share the id.
                triggers.append({**trig, "id": tid})
                options.append({"conditions": conditions, "sequence": seq})
    else:
        for slot in model.slots:
            entity_id = switch.entities.get(slot.slot)
            if not entity_id:
                continue
            for event_type, m in slot.events.items():
                trig = {
                    "trigger": "state",
                    "entity_id": entity_id,
                    "attribute": "event_type",
                    "to": event_type,
                }
                if m.raw == "tap":
                    add(trig, m.control, "press")
                elif m.gesture:
                    steps = f"{{{{ (trigger.to_state.attributes.{m.steps} | float(1) / {m.divide}) | round | int | max(1) }}}}" if m.steps else None
                    add(trig, m.control, m.gesture, steps)
                elif m.turn:
                    steps = f"{{{{ (trigger.to_state.attributes.{m.turn} | float(0) | abs / {m.divide}) | round | int | max(1) }}}}"
                    for gesture, cmp in (("turn_right", ">"), ("turn_left", "<")):
                        binding = switch.binding(m.control, gesture)
                        if binding is None:
                            continue
                        tid = f"{m.control}__{gesture}"
                        triggers.append({"trigger": "state", "entity_id": entity_id, "id": tid})
                        options.append(
                            {
                                "conditions": [
                                    {"condition": "trigger", "id": tid},
                                    {
                                        "condition": "template",
                                        "value_template": (
                                            f"{{{{ trigger.to_state.attributes.event_type == '{event_type}'"
                                            f" and (trigger.to_state.attributes.{m.turn} | float(0)) {cmp} 0 }}}}"
                                        ),
                                    },
                                ],
                                "sequence": [{"variables": {"steps": steps}}, *_actions(binding)],
                            }
                        )

    exported = {(o["conditions"][0]["id"]) for o in options}
    for control, gestures in switch.bindings.items():
        for gesture in gestures:
            if f"{control}__{gesture}" not in exported:
                name = model.control(control).name if model.control(control) else control
                left_out.append(f"{name}: {label(gesture)}")

    description = f"Exported from Button Blueprinter: {switch.name} ({model.name})."
    if switch.put_back:
        description += f" Putting things back after {switch.put_back['minutes']} minutes isn't exported."
    if left_out:
        description += " Not exported (needs Button Blueprinter's timing): " + ", ".join(left_out) + "."
    return {
        "alias": f"Buttons: {switch.name}",
        "description": description,
        "triggers": triggers,
        "conditions": [],
        "actions": [{"choose": options}] if options else [],
        "variables": {"steps": 1, "switch_scenes": scenes_of(switch.bindings)},
        "mode": "queued",
        "max": 10,
    }
