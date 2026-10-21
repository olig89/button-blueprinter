"""A device's own event, turned into a gesture (or a raw press for ``timing``).

No Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gestures import Gesture
from .models import EventMap, Slot


@dataclass(frozen=True)
class Raw:
    """A raw press for the timing engine."""

    control: str
    raw: str


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _steps(amount: float, divide: float) -> int:
    """At least one step for any movement; device units scaled to steps."""
    return max(1, round(abs(amount) / divide))


def from_event(slot: Slot, event_type: str | None, attributes: dict[str, Any]) -> Gesture | Raw | None:
    """What an event entity's new event means, or None if this model ignores it."""
    if not event_type:
        return None
    m: EventMap | None = slot.events.get(event_type)
    if m is None:
        return None
    control = m.control_for(attributes)
    if control is None:
        return None
    if m.raw:
        return Raw(control, m.raw)
    if m.turn:
        amount = _number(attributes.get(m.turn))
        if not amount:
            return None
        return Gesture(control, "turn_right" if amount > 0 else "turn_left", _steps(amount, m.divide))
    steps = 1
    if m.steps:
        amount = _number(attributes.get(m.steps))
        steps = _steps(amount, m.divide) if amount else 1
    return Gesture(control, m.gesture or "press", steps)
