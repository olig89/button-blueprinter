"""The words for what someone does to a control, and how the page says them.

Every device's own event names are turned into these (``translate.py``), so the
rest of Button Blueprinter never sees a device's vocabulary. No Home Assistant
imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# In the order the page lists them.
GESTURES: dict[str, str] = {
    "press": "Tap",
    "double_press": "Double tap",
    "triple_press": "Triple tap",
    "long_press": "Hold",
    "long_press_repeat": "While held",
    "long_press_release": "Let go after a hold",
    "turn_right": "Turn right",
    "turn_left": "Turn left",
    "face_up": "Lands face up",
    "shake": "Shake",
    "throw": "Throw",
    "slide": "Slide",
    "swipe_left": "Swipe left",
    "swipe_right": "Swipe right",
    "swipe_up": "Swipe up",
    "swipe_down": "Swipe down",
    "touch_left": "Touch left",
    "touch_right": "Touch right",
    "touch_top": "Touch top",
    "touch_bottom": "Touch bottom",
    "long_touch_left": "Long touch left",
    "long_touch_right": "Long touch right",
    "long_touch_top": "Long touch top",
    "long_touch_bottom": "Long touch bottom",
    "fly_left": "Wave left",
    "fly_right": "Wave right",
    "proximity": "Hand near",
}

# Gestures that carry a number of steps (how far the dial turned).
STEPPED = frozenset({"turn_right", "turn_left"})

# Raw inputs the timing engine turns into gestures (``timing.py``).
RAW_TAP = "tap"  # a finished short press; may become a double press
RAW_DOWN = "down"  # finger on: may become a tap or a hold
RAW_UP = "up"  # finger off
RAW = frozenset({RAW_TAP, RAW_DOWN, RAW_UP})


@dataclass(frozen=True)
class Gesture:
    """One gesture on one control."""

    control: str
    gesture: str
    steps: int = 1

    def as_dict(self) -> dict:
        return {"control": self.control, "gesture": self.gesture, "steps": self.steps}


def label(gesture: str) -> str:
    return GESTURES.get(gesture, gesture.replace("_", " ").capitalize())
