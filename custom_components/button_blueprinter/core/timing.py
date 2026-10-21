"""Tap, double tap and hold, made from raw presses, for devices that don't make them.

A device either sends gestures itself (a KNX plate's tap and hold addresses, the
BILRESA plugin's press / double / hold) or only raw events:

- ``tap``: a short press has finished (Hue ``short_release``, a KNX tap). It may
  still turn out to be the first half of a double tap.
- ``down`` / ``up``: a finger on, a finger off (the Nuimo's button). These may
  become a tap or a hold.

Rules:
- A tap fires at once when the control has no double-tap binding. Otherwise it
  waits ``double_window`` seconds for a second tap.
- A press held for ``hold_after`` seconds is a hold. While held it repeats every
  ``repeat_every`` seconds, at most ``max_repeats`` times (a safety stop for a
  lost "up"), and letting go after a hold is ``long_press_release``.

Pure: the caller passes the time in and asks when to call back (``next_deadline``).
No Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gestures import RAW_DOWN, RAW_TAP, RAW_UP, Gesture

DOUBLE_WINDOW = 0.4
HOLD_AFTER = 0.5
REPEAT_EVERY = 0.3
MAX_REPEATS = 100
_EPS = 1e-6  # deadlines compare a little early, so 1.1 + 0.3 counts as 1.4


@dataclass
class _State:
    tap_deadline: float | None = None  # a tap waiting to see if a second one comes
    down_at: float | None = None
    hold_deadline: float | None = None
    holding: bool = False
    next_repeat: float | None = None
    repeats: int = 0


class Timing:
    def __init__(
        self,
        double_window: float = DOUBLE_WINDOW,
        hold_after: float = HOLD_AFTER,
        repeat_every: float = REPEAT_EVERY,
        max_repeats: int = MAX_REPEATS,
    ) -> None:
        self.double_window = double_window
        self.hold_after = hold_after
        self.repeat_every = repeat_every
        self.max_repeats = max_repeats
        self._states: dict[str, _State] = {}

    def _state(self, control: str) -> _State:
        return self._states.setdefault(control, _State())

    def _tap(self, now: float, control: str, wants_double: bool) -> list[Gesture]:
        st = self._state(control)
        if st.tap_deadline is not None:
            st.tap_deadline = None
            return [Gesture(control, "double_press")]
        if not wants_double:
            return [Gesture(control, "press")]
        st.tap_deadline = now + self.double_window
        return []

    def feed(self, now: float, control: str, raw: str, wants_double: bool = False) -> list[Gesture]:
        """A raw event. Returns the gestures it completes."""
        out = self.due(now)
        st = self._state(control)
        if raw == RAW_TAP:
            return out + self._tap(now, control, wants_double)
        if raw == RAW_DOWN:
            if st.down_at is not None:  # a second "down" without an "up": start again
                out += self._finish_hold(control)
            st.down_at = now
            st.hold_deadline = now + self.hold_after
            return out
        if raw == RAW_UP:
            if st.down_at is None:
                return out  # an "up" we never saw go down
            if st.holding:
                return out + self._finish_hold(control)
            st.down_at = st.hold_deadline = None
            return out + self._tap(now, control, wants_double)
        raise ValueError(f"unknown raw event {raw!r}")

    def _finish_hold(self, control: str) -> list[Gesture]:
        st = self._state(control)
        out = [Gesture(control, "long_press_release")] if st.holding else []
        st.down_at = st.hold_deadline = st.next_repeat = None
        st.holding = False
        st.repeats = 0
        return out

    def due(self, now: float) -> list[Gesture]:
        """Gestures whose time has come: a lone tap, a hold starting, a repeat."""
        out: list[Gesture] = []
        now += _EPS
        for control, st in self._states.items():
            if st.tap_deadline is not None and now >= st.tap_deadline:
                st.tap_deadline = None
                out.append(Gesture(control, "press"))
            if st.hold_deadline is not None and not st.holding and now >= st.hold_deadline:
                if st.tap_deadline is not None:  # the first tap of a double, then a hold
                    st.tap_deadline = None
                    out.append(Gesture(control, "press"))
                st.holding = True
                st.next_repeat = st.hold_deadline + self.repeat_every  # on the hold's own clock
                st.hold_deadline = None
                out.append(Gesture(control, "long_press"))
            while st.holding and st.next_repeat is not None and now >= st.next_repeat:
                if st.repeats >= self.max_repeats:
                    st.next_repeat = None
                    break
                st.repeats += 1
                st.next_repeat += self.repeat_every
                out.append(Gesture(control, "long_press_repeat"))
        return out

    def next_deadline(self) -> float | None:
        times = [
            t
            for st in self._states.values()
            for t in (st.tap_deadline, st.hold_deadline, st.next_repeat if st.holding else None)
            if t is not None
        ]
        return min(times) if times else None

    def reset(self) -> None:
        self._states.clear()
