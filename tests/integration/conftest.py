"""A small house: the Small Bathroom plate, a Hue dimmer, a Nuimo and a light or two.

KNX itself isn't loaded in the tests; telegrams are handed straight to
``Blueprinter.handle_telegram`` and ``knx.send`` is a recorder.
"""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.setup import async_setup_component

from custom_components.button_blueprinter.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class House:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict]] = []
        self.entry: MockConfigEntry | None = None
        self._events = 0

    async def handle(self, call) -> None:
        self.calls.append((call.domain, call.service, dict(call.data)))

    def services(self, domain: str, service: str | None = None) -> list[dict]:
        return [d for (dom, srv, d) in self.calls if dom == domain and (service is None or srv == service)]

    @property
    def bp(self):
        return self.entry.runtime_data

    async def press(self, entity_id: str, event_type: str, **attrs) -> None:
        """A new event on an event entity: its state becomes a new timestamp."""
        self._events += 1
        self.hass.states.async_set(entity_id, f"2026-10-08T12:{self._events // 60:02d}:{self._events % 60:02d}.000+00:00", {"event_type": event_type, **attrs})
        await self.hass.async_block_till_done()


def _tap(ga, tid):
    return {"trigger": "event", "event_type": "knx_event", "event_data": {"destination": ga}, "id": tid}


def _opt(tid, action):
    return {"conditions": [{"condition": "trigger", "id": tid}], "sequence": [action]}


# A typical automation for this plate, cut down to three gestures.
OLD_SMALL_BATHROOM = {
    "id": "1000000000001",
    "alias": "Wall buttons: Small Bathroom (1.1.31)",
    "triggers": [_tap("6/0/40", "b1_tap"), _tap("6/1/40", "b1_hold"), _tap("6/0/41", "b2_tap")],
    "actions": [
        {
            "choose": [
                _opt("b1_tap", {"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_ceiling"}}),
                _opt(
                    "b1_hold",
                    {"action": "light.turn_on", "target": {"entity_id": ["light.small_bathroom_ceiling"]}, "data": {"brightness_pct": 100}},
                ),
                _opt("b2_tap", {"action": "light.toggle", "target": {"entity_id": "light.small_bathroom_ceiling"}}),
            ]
        }
    ],
    "mode": "queued",
}


@pytest.fixture
async def house(hass: HomeAssistant) -> House:
    built = House(hass)
    for domain, services in {
        "light": ("toggle", "turn_on", "turn_off"),
        "homeassistant": ("turn_on", "turn_off", "toggle"),
        "scene": ("turn_on",),
        "knx": ("send",),
        "media_player": ("volume_up", "volume_down", "media_play_pause"),
    }.items():
        for service in services:
            hass.services.async_register(domain, service, built.handle)
    ar.async_get(hass).async_get_or_create("Small Bathroom")
    hass.states.async_set("light.small_bathroom_ceiling", "off")
    hass.states.async_set("light.small_bathroom_mirror", "off")
    for i in range(1, 5):
        hass.states.async_set(f"event.office_dimmer_button_{i}", "unknown", {"event_type": None})
    hass.states.async_set("event.nuimo_control_button", "2026-10-08T11:00:00.000+00:00", {"event_type": "release"})
    hass.states.async_set("binary_sensor.office_bright_active", "off")
    assert await async_setup_component(hass, "automation", {"automation": [OLD_SMALL_BATHROOM]})
    built.entry = MockConfigEntry(domain=DOMAIN, title="Button Blueprinter", data={})
    built.entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(built.entry.entry_id)
    await hass.async_block_till_done()
    return built
