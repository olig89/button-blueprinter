"""The working part: loads models and switches, listens to buttons, runs bindings.

Inputs:
- KNX plates: the KNX integration's own ``knx.telegram`` trigger, attached in
  code, so no ``knx: event:`` configuration is needed. Writes on a switch's tap
  and hold addresses are presses; reads on its LED addresses are answered.
- Event entities (Hue, Matter, the BILRESA plugin, the Nuimo): state changes,
  where the new state is a new event. A state restored at start-up, or coming
  back from unavailable, is not a press.
- Zigbee2MQTT devices (the Aqara cube): the device's own topic, found from its
  Home Assistant device (Zigbee2MQTT names the device after its friendly name),
  so a rename in Zigbee2MQTT moves the subscription with it. A message with an
  ``action`` is an event; the rest of the message are its attributes.

Each gesture is looked up on its switch and then, by the switch's mode: run
(``live``), logged as "would run" (``dry_run``), or ignored (``off``). Every
gesture goes in the log, the page's way of showing what happened.

Put back (``core/putback.py``): on a switch whose presses are for now, the
first press saves how the lights it touches look, and each press restarts the
clock. A light stays this switch's while its changes carry the contexts of
this switch's runs; any other change makes it someone else's. When the clock
runs out, the switch's lights go back. The saved looks and the time are
stored, so a restart doesn't lose them (the contexts are, so after a restart
only changes made since count).
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_COMPONENT_LOADED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.helpers.trigger import async_initialize_triggers, async_validate_trigger_config
from homeassistant.util import dt as dt_util

from .const import LOG_SIZE, NAME, SIGNAL_CHANGED, STORAGE_KEY, STORAGE_VERSION, Z2M_BASE_TOPIC
from .core import knx as knx_addr
from .core.export import to_automation
from .core.gestures import GESTURES, STEPPED, Gesture, label
from .core.icons import IconSet, IconSetError, parse_icon_set
from .core.models import Model, ModelError, parse_model
from .core.palette import MENU, from_actions, scenes_of, to_actions
from .core.putback import applies as put_back_applies, look, restorable, restore_actions, touched
from .core.requests import changed_where, full_look, same_look, steps as look_steps
from .core.switches import Switch, SwitchError, check, check_binding, check_looks, led_value, new_id
from .core.timing import Timing
from .core.translate import Raw, from_event

_LOGGER = logging.getLogger(__name__)
MODELS_DIR = Path(__file__).parent / "models"
ICON_SETS_DIR = Path(__file__).parent / "icon_sets"
ICON_FILES_FOLDER = "button_blueprinter_icons"  # in HA's config folder: <set id>/<file>, not shipped


class BlueprinterError(Exception):
    """Something a person asked for can't be done. ``code`` is for the page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_models(folder: Path) -> tuple[dict[str, Model], list[str]]:
    """Every model file in the folder. A broken file is reported, not fatal."""
    models: dict[str, Model] = {}
    errors: list[str] = []
    for path in sorted(folder.glob("*.yaml")):
        try:
            model = parse_model(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
        except (ModelError, yaml.YAMLError, OSError) as err:
            errors.append(str(err))
            continue
        if model.id != path.stem:
            errors.append(f"{path.name}: its id is '{model.id}', it should match the file name")
            continue
        models[model.id] = model
    return models, errors


def load_icon_sets(folder: Path, files_root: Path) -> tuple[dict[str, IconSet], list[str], dict[str, list[str]]]:
    """Every icon set, and which of each set's pictures are installed in HA."""
    sets: dict[str, IconSet] = {}
    errors: list[str] = []
    installed: dict[str, list[str]] = {}
    for path in sorted(folder.glob("*.yaml")):
        try:
            icon_set = parse_icon_set(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
        except (IconSetError, yaml.YAMLError, OSError) as err:
            errors.append(str(err))
            continue
        sets[icon_set.id] = icon_set
        here = files_root / icon_set.id
        installed[icon_set.id] = [
            i.id for i in icon_set.icons.values() if i.file and (here / i.file).is_file()
        ]
    return sets, errors, installed


class Blueprinter:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.models: dict[str, Model] = {}
        self.model_errors: list[str] = []
        self.icon_sets: dict[str, IconSet] = {}
        self.icon_files: dict[str, list[str]] = {}  # set id -> icon ids whose real picture is installed
        self.switches: dict[str, Switch] = {}
        self.log: deque[dict[str, Any]] = deque(maxlen=LOG_SIZE)
        self.knx_state = "not needed"
        self.mqtt_state = "not needed"
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listen_unsubs: list[CALLBACK_TYPE] = []
        self._knx_unsub: CALLBACK_TYPE | None = None
        self._timing: dict[str, Timing] = {}
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._scripts: dict[tuple[str, str, str], Script] = {}
        self._knx_inputs: dict[str, tuple[str, str, str]] = {}  # address -> switch, control, channel
        self._knx_leds: dict[str, tuple[str, str]] = {}  # address -> switch, control
        self._entity_slots: dict[str, tuple[str, str]] = {}  # entity -> switch, slot
        self._z2m: dict[str, str] = {}  # Home Assistant device id -> switch (zigbee2mqtt models)
        self._led_sources: dict[str, list[tuple[str, str]]] = {}  # entity -> [(switch, control)]
        self._started = False
        # Put back: switch -> {"until": iso time, "lights": {entity: saved look}}; stored.
        self._plays: dict[str, dict[str, Any]] = {}
        self._play_contexts: dict[str, set[str]] = {}  # switch -> contexts of its runs since the play began
        self._play_timers: dict[str, CALLBACK_TYPE] = {}
        self._play_unsub: CALLBACK_TYPE | None = None
        # Dial turns that arrive while a turn of the same control is running: net steps (+ right, - left).
        self._turning: dict[tuple[str, str], int] = {}

    # ---- start and stop ---------------------------------------------------------

    async def async_start(self) -> None:
        self.models, self.model_errors = await self.hass.async_add_executor_job(load_models, MODELS_DIR)
        self.icon_sets, set_errors, self.icon_files = await self.hass.async_add_executor_job(
            load_icon_sets, ICON_SETS_DIR, Path(self.hass.config.path(ICON_FILES_FOLDER))
        )
        self.model_errors += set_errors
        for model in list(self.models.values()):
            if model.icon_set and model.icon_set not in self.icon_sets:
                self.model_errors.append(f"{model.id}: icon set '{model.icon_set}' not found")
            elif model.icon_set and (unknown := set(model.icon_only) - set(self.icon_sets[model.icon_set].icons)):
                self.model_errors.append(f"{model.id}: not in its icon set: {', '.join(sorted(unknown))}")
        for err in self.model_errors:
            _LOGGER.warning("Model file not loaded: %s", err)
        data = await self._store.async_load() or {}
        for raw in data.get("switches", []):
            try:
                switch = Switch.from_dict(raw)
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.warning("A stored switch couldn't be read and was skipped: %s", err)
                continue
            self.switches[switch.id] = switch
        self._plays = {
            sid: {"until": str(p.get("until") or ""), "lights": dict(p.get("lights") or {})}
            for sid, p in (data.get("put_back") or {}).items()
            if isinstance(p, dict)
        }
        await self._async_rebuild()

        @callback
        def _started(_hass: HomeAssistant) -> None:
            self._started = True
            self.hass.async_create_task(self._async_send_all_leds())
            for switch_id in list(self._plays):
                self._arm(switch_id)
            self._track_plays()

        self._unsubs.append(async_at_started(self.hass, _started))

        @callback
        def _component_loaded(event: Event) -> None:
            if event.data.get("component") == "knx" and self._knx_unsub is None and (self._knx_inputs or self._knx_leds):
                self.hass.async_create_task(self._async_attach_knx())
            if event.data.get("component") == "mqtt" and self._z2m and self.mqtt_state != "listening":
                self.hass.async_create_task(self._async_rebuild())

        self.entry.async_on_unload(self.hass.bus.async_listen(EVENT_COMPONENT_LOADED, _component_loaded))

        @callback
        def _device_changed(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
            # A rename in Zigbee2MQTT renames the device, and so its topic.
            if event.data["device_id"] in self._z2m and "name" in (event.data.get("changes") or {}):
                self.hass.async_create_task(self._async_rebuild())

        self.entry.async_on_unload(self.hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _device_changed))

    async def async_stop(self) -> None:
        self._detach()
        for cancel in self._play_timers.values():
            cancel()
        self._play_timers.clear()
        if self._play_unsub:
            self._play_unsub()
            self._play_unsub = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for script in self._scripts.values():
            await script.async_stop()
        self._scripts.clear()

    def _detach(self) -> None:
        for unsub in self._listen_unsubs:
            unsub()
        self._listen_unsubs = []
        if self._knx_unsub:
            self._knx_unsub()
            self._knx_unsub = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    async def _async_rebuild(self) -> None:
        """Listen to exactly what the switches need, after any change."""
        self._detach()
        for script in self._scripts.values():
            self.hass.async_create_task(script.async_stop())
        self._scripts.clear()
        self._timing = {sid: self._timing.get(sid, Timing()) for sid in self.switches}
        for switch_id in list(self._plays):  # deleted, or no longer puts things back: forget it
            if not (switch := self.switches.get(switch_id)) or not switch.put_back:
                self._end_play(switch_id)
        self._knx_inputs, self._knx_leds, self._entity_slots, self._led_sources = {}, {}, {}, {}
        self._z2m = {}
        for switch in self.switches.values():
            model = self.models.get(switch.model)
            if model is None or switch.mode == "off":
                continue
            if model.input == "knx":
                try:
                    for address, (control, channel) in knx_addr.addresses(model, switch.knx).items():
                        self._knx_inputs[address] = (switch.id, control, channel)
                    for control, address in knx_addr.led_addresses(model, switch.knx).items():
                        if control in switch.leds:
                            self._knx_leds[address] = (switch.id, control)
                            source = switch.leds[control]["entity_id"]
                            self._led_sources.setdefault(source, []).append((switch.id, control))
                except knx_addr.AddressError as err:
                    _LOGGER.warning("%s: %s", switch.name, err)
            elif model.input == "zigbee2mqtt":
                if switch.device:
                    self._z2m[switch.device] = switch.id
            else:
                for slot, entity_id in switch.entities.items():
                    self._entity_slots[entity_id] = (switch.id, slot)
        if self._entity_slots:
            self._listen_unsubs.append(
                async_track_state_change_event(self.hass, list(self._entity_slots), self._on_event_entity)
            )
        if self._led_sources:
            self._listen_unsubs.append(
                async_track_state_change_event(self.hass, list(self._led_sources), self._on_led_source)
            )
        if self._knx_inputs or self._knx_leds:
            await self._async_attach_knx()
        else:
            self.knx_state = "not needed"
        await self._async_attach_mqtt()
        self._signal()

    def z2m_topic(self, device_id: str | None) -> str | None:
        device = dr.async_get(self.hass).async_get(device_id) if device_id else None
        return f"{Z2M_BASE_TOPIC}/{device.name}" if device and device.name else None

    async def _async_attach_mqtt(self) -> None:
        if not self._z2m:
            self.mqtt_state = "not needed"
            return
        if "mqtt" not in self.hass.config.components:
            self.mqtt_state = "waiting for the MQTT integration"
            return
        from homeassistant.components import mqtt  # only when a switch needs it

        problems = []
        for device_id in self._z2m:
            topic = self.z2m_topic(device_id)
            if topic is None:
                problems.append(f"device {device_id} not found")
                continue

            @callback
            def _message(msg: Any, device_id: str = device_id) -> None:
                try:
                    payload = json.loads(msg.payload)
                except (TypeError, ValueError):
                    return
                if isinstance(payload, dict):
                    self.handle_z2m(device_id, payload)

            try:
                self._listen_unsubs.append(await mqtt.async_subscribe(self.hass, topic, _message))
            except Exception as err:  # noqa: BLE001 - MQTT not ready or not set up; say so on the page
                problems.append(f"couldn't subscribe to {topic}: {err}")
        self.mqtt_state = "; ".join(problems) if problems else "listening"
        for problem in problems:
            _LOGGER.warning("Zigbee2MQTT: %s", problem)

    async def _async_attach_knx(self) -> None:
        if "knx" not in self.hass.config.components:
            self.knx_state = "waiting for the KNX integration"
            self._signal()
            return
        config: list[dict[str, Any]] = []
        if self._knx_inputs:
            config.append(
                {
                    "trigger": "knx.telegram",
                    "destination": sorted(self._knx_inputs),
                    "group_value_read": False,
                    "group_value_response": False,
                    "outgoing": False,
                }
            )
        if self._knx_leds:
            config.append(
                {
                    "trigger": "knx.telegram",
                    "destination": sorted(self._knx_leds),
                    "group_value_write": False,
                    "group_value_response": False,
                    "outgoing": False,
                }
            )
        try:
            # The schema turns the `trigger:` key into `platform:`, which the helpers below need.
            validated = await async_validate_trigger_config(self.hass, cv.TRIGGER_SCHEMA(config))
            self._knx_unsub = await async_initialize_triggers(
                self.hass, validated, self._on_knx, "button_blueprinter", NAME, _knx_log
            )
        except Exception as err:  # noqa: BLE001 - HA's validators raise several kinds; all mean "not valid"
            self.knx_state = f"couldn't listen to KNX: {err}"
            _LOGGER.warning("Couldn't listen to KNX telegrams: %s", err)
        else:
            self.knx_state = "listening"
        self._signal()

    # ---- inputs -------------------------------------------------------------------

    async def _on_knx(self, run_variables: dict[str, Any], context: Context | None = None) -> None:
        trigger = run_variables.get("trigger") or {}
        self.handle_telegram(str(trigger.get("destination", "")), str(trigger.get("telegramtype", "")))

    @callback
    def handle_telegram(self, destination: str, telegram_type: str) -> None:
        """A telegram from the bus (incoming only)."""
        if telegram_type == "GroupValueRead":
            if destination in self._knx_leds:
                switch_id, control = self._knx_leds[destination]
                switch = self.switches.get(switch_id)
                if switch and switch.mode == "live":
                    self.hass.async_create_task(self._async_send_led(switch, control, response=True))
            return
        if telegram_type != "GroupValueWrite" or destination not in self._knx_inputs:
            return
        switch_id, control, channel = self._knx_inputs[destination]
        switch = self.switches.get(switch_id)
        model = self.models.get(switch.model) if switch else None
        if not switch or not model:
            return
        if channel == "tap":
            self._feed(switch, Raw(control, "tap"), destination)
        else:
            self._feed(switch, Gesture(control, model.knx.get(channel, "long_press")), destination)

    @callback
    def _on_event_entity(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if old is None or old.state == STATE_UNAVAILABLE or old.state == new.state:
            return  # restored at start-up, back from unavailable, or only attributes changed
        self.handle_event(entity_id, new.attributes.get("event_type"), dict(new.attributes))

    @callback
    def handle_event(self, entity_id: str, event_type: str | None, attributes: dict[str, Any]) -> None:
        if entity_id not in self._entity_slots:
            return
        switch_id, slot_id = self._entity_slots[entity_id]
        switch = self.switches.get(switch_id)
        model = self.models.get(switch.model) if switch else None
        slot = model.slot(slot_id) if model else None
        if not switch or not slot:
            return
        item = from_event(slot, event_type, attributes)
        if item is not None:
            self._feed(switch, item, f"{entity_id}: {event_type}")

    @callback
    def handle_z2m(self, device_id: str, payload: dict[str, Any]) -> None:
        """A Zigbee2MQTT message from a device. Only messages with an action are events."""
        action = payload.get("action")
        switch = self.switches.get(self._z2m.get(device_id, ""))
        model = self.models.get(switch.model) if switch else None
        if not isinstance(action, str) or not action or not switch or not model or not model.slots:
            return
        item = from_event(model.slots[0], action, payload)
        if item is not None:
            self._feed(switch, item, f"{switch.name}: {action}")

    # ---- gestures -----------------------------------------------------------------

    @callback
    def _feed(self, switch: Switch, item: Gesture | Raw, source: str) -> None:
        if isinstance(item, Raw):
            timing = self._timing.setdefault(switch.id, Timing())
            gestures = timing.feed(time.monotonic(), item.control, item.raw, switch.wants_double(item.control))
            self._schedule(switch.id)
        else:
            gestures = [item]
        for gesture in gestures:
            self.fire(switch, gesture, source)

    @callback
    def _schedule(self, switch_id: str) -> None:
        if cancel := self._timers.pop(switch_id, None):
            cancel()
        timing = self._timing.get(switch_id)
        deadline = timing.next_deadline() if timing else None
        if deadline is None:
            return

        @callback
        def _due(_now: datetime) -> None:
            self._timers.pop(switch_id, None)
            switch = self.switches.get(switch_id)
            if switch is None or timing is None:
                return
            # At least the deadline: a timer can fire a hair early, and a test clock doesn't move.
            for gesture in timing.due(max(time.monotonic(), deadline)):
                self.fire(switch, gesture, "timing")
            self._schedule(switch_id)

        self._timers[switch_id] = async_call_later(self.hass, max(0.0, deadline - time.monotonic()), _due)

    @callback
    def fire(self, switch: Switch, gesture: Gesture, source: str) -> dict[str, Any]:
        """Act on one gesture by the switch's mode, and log it."""
        model = self.models.get(switch.model)
        control = model.control(gesture.control) if model else None
        entry: dict[str, Any] = {
            "at": dt_util.utcnow().isoformat(),
            "switch": switch.id,
            "control": gesture.control,
            "control_name": control.name if control else gesture.control,
            "gesture": gesture.gesture,
            "gesture_name": label(gesture.gesture),
            "steps": gesture.steps,
            "source": source,
            "mode": switch.mode,
        }
        binding = switch.binding(gesture.control, gesture.gesture)
        if switch.mode == "off":
            entry["result"] = "off"
        elif switch.is_fixed(gesture.control, gesture.gesture):
            entry["result"] = "fixed"
            entry["detail"] = switch.fixed[gesture.control][gesture.gesture]
        elif binding is None:
            entry["result"] = "nothing set"
        elif switch.mode == "dry_run":
            entry["result"] = "would run"
        elif gesture.gesture in STEPPED:
            entry["result"] = "ran"
            self._turn(switch, gesture, entry)
        else:
            entry["result"] = "ran"
            self.hass.async_create_task(self._async_run(switch, gesture, binding, entry))
        self.log.append(entry)
        self._signal()
        return entry

    @callback
    def _turn(self, switch: Switch, gesture: Gesture, entry: dict) -> None:
        """A dial turn. Turns that arrive while one is running are added up and sent as one.

        A dial can report several turns a second, faster than a light takes each
        command: one command per turn falls further behind the longer the dial
        turns, and right and left could overtake each other. Now at most one
        turn per control runs, and the next carries the net of everything since.
        """
        key = (switch.id, gesture.control)
        signed = gesture.steps if gesture.gesture == "turn_right" else -gesture.steps
        if key in self._turning:
            self._turning[key] += signed
            entry["detail"] = "added to the turn being sent"
            return
        self._turning[key] = 0
        self.hass.async_create_task(self._async_turn(switch.id, gesture.control, signed, entry))

    async def _async_turn(self, switch_id: str, control: str, signed: int, entry: dict) -> None:
        key = (switch_id, control)
        try:
            while signed:
                switch = self.switches.get(switch_id)
                if switch is None or switch.mode != "live":
                    return
                gesture = Gesture(control, "turn_right" if signed > 0 else "turn_left", abs(signed))
                if binding := switch.binding(control, gesture.gesture):
                    # A later turn can go the other way: name its run after its own gesture.
                    run_entry = entry if gesture.gesture == entry["gesture"] else {**entry, "gesture": gesture.gesture, "gesture_name": label(gesture.gesture)}
                    await self._async_run(switch, gesture, binding, run_entry)
                signed, self._turning[key] = self._turning.get(key, 0), 0
        finally:
            self._turning.pop(key, None)

    async def _async_compile(self, binding: dict) -> list[dict]:
        actions = to_actions(binding["menu"]) if "menu" in binding else binding["actions"]
        return await async_validate_actions_config(self.hass, cv.SCRIPT_SCHEMA(actions))

    async def _async_run(self, switch: Switch, gesture: Gesture, binding: dict, entry: dict) -> None:
        key = (switch.id, gesture.control, gesture.gesture)
        try:
            script = self._scripts.get(key)
            if script is None:
                script = Script(
                    self.hass,
                    await self._async_compile(binding),
                    f"{NAME}: {switch.name} {entry['control_name']} {entry['gesture_name']}",
                    "button_blueprinter",
                    script_mode="queued",
                    max_runs=10,
                    logger=_LOGGER,
                )
                self._scripts[key] = script
            variables = {
                "steps": gesture.steps,
                "gesture": gesture.gesture,
                "control": gesture.control,
                "switch": switch.id,
                "switch_scenes": scenes_of(switch.bindings),
            }
            context = Context()
            if put_back_applies(switch.put_back, gesture.control) and (binding.get("menu") or {}).get("kind") != "put_back":
                self._play_press(switch, binding, context)
            await script.async_run(variables, context)
        except Exception as err:  # noqa: BLE001 - shown on the page, never raised into the bus
            entry["result"] = "error"
            entry["detail"] = str(err)
            _LOGGER.warning("%s %s %s failed: %s", switch.name, entry["control_name"], entry["gesture_name"], err)
            self._signal()

    # ---- put back -------------------------------------------------------------------

    def _expand(self, entity_ids: list[str]) -> list[str]:
        """Scenes become their entities; only what can be put back is kept."""
        out: list[str] = []
        for entity_id in entity_ids:
            if entity_id.startswith("scene."):
                state = self.hass.states.get(entity_id)
                members = list(state.attributes.get("entity_id") or []) if state else []
            else:
                members = [entity_id]
            out += [m for m in members if restorable(m) and m not in out]
        return out

    @callback
    def _play_press(self, switch: Switch, binding: dict, context: Context) -> None:
        """A press that is for now: save what it touches (once), own its changes, restart the clock."""
        play = self._plays.get(switch.id)
        entities = self._expand(touched(binding))
        if play is None and not entities:
            return  # nothing to put back, and nothing started yet
        if play is None:
            play = self._plays[switch.id] = {"until": "", "lights": {}}
            self._play_contexts[switch.id] = set()
        for entity_id in entities:
            if entity_id not in play["lights"] and (state := self.hass.states.get(entity_id)):
                if (saved := look(entity_id, state.state, dict(state.attributes))) is not None:
                    play["lights"][entity_id] = saved
        if not play["lights"]:
            self._end_play(switch.id)
            return
        self._play_contexts.setdefault(switch.id, set()).add(context.id)
        play["until"] = (dt_util.utcnow() + timedelta(minutes=switch.put_back["minutes"])).isoformat()
        self._arm(switch.id)
        self._track_plays()
        self._save_plays()

    @callback
    def _arm(self, switch_id: str) -> None:
        if cancel := self._play_timers.pop(switch_id, None):
            cancel()
        play = self._plays.get(switch_id)
        until = dt_util.parse_datetime(play["until"]) if play and play.get("until") else None
        if until is None:
            return

        @callback
        def _due(_now: datetime) -> None:
            self._play_timers.pop(switch_id, None)
            self.hass.async_create_task(self.async_put_back(switch_id, "time"))

        self._play_timers[switch_id] = async_track_point_in_utc_time(self.hass, _due, max(until, dt_util.utcnow()))

    @callback
    def _track_plays(self) -> None:
        if self._play_unsub:
            self._play_unsub()
            self._play_unsub = None
        watched = sorted({e for p in self._plays.values() for e in p["lights"]})
        if watched:
            self._play_unsub = async_track_state_change_event(self.hass, watched, self._on_played_change)

    @callback
    def _on_played_change(self, event: Event[EventStateChangedData]) -> None:
        """A change to a light being put back later: ours, or now someone else's."""
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None:
            return
        before = look(entity_id, old.state, dict(old.attributes))
        after = look(entity_id, new.state, dict(new.attributes))
        if before is None or after is None or before == after:
            return  # unavailable for a moment, or nothing that is put back changed
        changed = False
        for switch_id, play in list(self._plays.items()):
            if entity_id not in play["lights"]:
                continue
            mine = self._play_contexts.get(switch_id, set())
            if new.context.id in mine or (new.context.parent_id and new.context.parent_id in mine):
                continue
            del play["lights"][entity_id]  # someone else's now: leave it be
            changed = True
            if not play["lights"]:
                self._end_play(switch_id)
        if changed:
            self._track_plays()
            self._save_plays()

    @callback
    def _end_play(self, switch_id: str) -> None:
        self._plays.pop(switch_id, None)
        self._play_contexts.pop(switch_id, None)
        if cancel := self._play_timers.pop(switch_id, None):
            cancel()

    async def async_put_back(self, switch_id: str, why: str) -> dict[str, Any]:
        """Put a switch's lights back now (its time ran out, or someone asked)."""
        play = self._plays.get(switch_id)
        self._end_play(switch_id)
        self._track_plays()
        if not play or not play["lights"]:
            self._save_plays()
            return {"result": "nothing to put back"}
        context = Context()
        failed = []
        for entity_id, saved in play["lights"].items():
            for action in restore_actions(entity_id, saved):
                domain, service = action["action"].split(".", 1)
                try:
                    await self.hass.services.async_call(
                        domain, service, {**action.get("data", {}), "entity_id": entity_id}, blocking=True, context=context
                    )
                except Exception as err:  # noqa: BLE001 - one light failing mustn't stop the others
                    failed.append(entity_id)
                    _LOGGER.warning("Couldn't put %s back: %s", entity_id, err)
        switch = self.switches.get(switch_id)
        names = [self._entity_name(e) for e in play["lights"]]
        self.log.append(
            {
                "at": dt_util.utcnow().isoformat(),
                "switch": switch_id,
                "control": "",
                "control_name": "",
                "gesture": "put_back",
                "gesture_name": "Put back",
                "steps": 1,
                "source": why,
                "mode": switch.mode if switch else "",
                "result": "error" if failed else "put back",
                "detail": ("Couldn't put back: " + ", ".join(failed)) if failed else ", ".join(names),
            }
        )
        self._save_plays()
        return {"result": "put back", "lights": list(play["lights"])}

    def _entity_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return str(state.attributes.get("friendly_name") or entity_id) if state else entity_id

    @callback
    def _save_plays(self) -> None:
        self._store.async_delay_save(self._stored, 2)
        self._signal()

    def _stored(self) -> dict[str, Any]:
        return {"switches": [s.as_dict() for s in self.switches.values()], "put_back": self._plays}

    # ---- LEDs ---------------------------------------------------------------------

    @callback
    def _on_led_source(self, event: Event[EventStateChangedData]) -> None:
        for switch_id, control in self._led_sources.get(event.data["entity_id"], []):
            switch = self.switches.get(switch_id)
            if switch and switch.mode == "live":
                self.hass.async_create_task(self._async_send_led(switch, control))

    async def _async_send_all_leds(self) -> None:
        for switch in list(self.switches.values()):
            if switch.mode != "live":
                continue
            for control in switch.leds:
                await self._async_send_led(switch, control)

    def led_state(self, switch: Switch, control: str) -> int:
        rule = switch.leds.get(control)
        if not rule:
            return 0
        state = self.hass.states.get(rule["entity_id"])
        return led_value(rule, state.state if state else None)

    async def _async_send_led(self, switch: Switch, control: str, response: bool = False) -> None:
        model = self.models.get(switch.model)
        if model is None or not self.hass.services.has_service("knx", "send"):
            return
        address = knx_addr.led_addresses(model, switch.knx).get(control)
        if not address:
            return
        data: dict[str, Any] = {"address": address, "payload": self.led_state(switch, control)}
        if response:
            data["response"] = True
        try:
            await self.hass.services.async_call("knx", "send", data, blocking=True)
        except Exception as err:  # noqa: BLE001 - an LED is never worth failing anything for
            _LOGGER.warning("%s: LED %s not sent: %s", switch.name, address, err)

    # ---- changes from the page ------------------------------------------------------

    def _signal(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHANGED)

    async def _async_save(self) -> None:
        await self._store.async_save(self._stored())

    def _model(self, model_id: str) -> Model:
        model = self.models.get(model_id)
        if model is None:
            raise BlueprinterError("unknown_model", "That switch model isn't known")
        return model

    def _switch(self, switch_id: str) -> Switch:
        switch = self.switches.get(switch_id)
        if switch is None:
            raise BlueprinterError("unknown_switch", "That switch no longer exists. Reload the page.")
        return switch

    def _clash(self, switch: Switch, model: Model) -> None:
        """Two switches may not listen to the same address or entity."""
        mine: set[str] = set()
        if model.input == "knx":
            mine = set(knx_addr.addresses(model, switch.knx)) | set(knx_addr.led_addresses(model, switch.knx).values())
        elif model.input == "zigbee2mqtt":
            mine = {f"device {switch.device}"} if switch.device else set()
        else:
            mine = set(switch.entities.values())
        for other in self.switches.values():
            if other.id == switch.id or (om := self.models.get(other.model)) is None:
                continue
            try:
                if om.input == "knx":
                    theirs = set(knx_addr.addresses(om, other.knx)) | set(knx_addr.led_addresses(om, other.knx).values())
                elif om.input == "zigbee2mqtt":
                    theirs = {f"device {other.device}"} if other.device else set()
                else:
                    theirs = set(other.entities.values())
            except knx_addr.AddressError:
                continue
            if shared := mine & theirs:
                raise BlueprinterError("clash", f"{sorted(shared)[0]} is already used by {other.name}")

    async def _async_check_actions(self, switch: Switch) -> None:
        for control, gestures in switch.bindings.items():
            for gesture, binding in gestures.items():
                try:
                    await self._async_compile(binding)
                except Exception as err:  # noqa: BLE001 - HA's validators raise several kinds; all mean "not valid"
                    raise BlueprinterError("invalid_actions", f"{control} {label(gesture)}: {err}") from err

    async def async_save_switch(self, data: dict[str, Any]) -> Switch:
        """Add or change a switch (admins). Bindings are kept unless given."""
        existing = self.switches.get(str(data.get("id") or ""))
        model = self._model(str(data.get("model") or (existing.model if existing else "")))
        base = existing.as_dict() if existing else {"bindings": {}, "mode": "dry_run"}
        for key in ("name", "area_id", "mode", "knx", "entities", "device", "looks", "wanted", "fixed", "leds", "bindings", "put_back"):
            if key in data:
                base[key] = data[key]
        base["model"] = model.id
        base["id"] = existing.id if existing else new_id(str(base.get("name") or model.name), set(self.switches))
        switch = Switch.from_dict(base)
        if existing and existing.model != switch.model and "bindings" not in data:
            switch.bindings = {}  # another model's buttons mean nothing here
        try:
            check(switch, model, self.icon_sets)
        except SwitchError as err:
            raise BlueprinterError("invalid", str(err)) from err
        self._clash(switch, model)
        await self._async_check_actions(switch)
        self.switches[switch.id] = switch
        await self._async_save()
        await self._async_rebuild()
        return switch

    async def async_delete_switch(self, switch_id: str) -> None:
        self._switch(switch_id)
        del self.switches[switch_id]
        self._timing.pop(switch_id, None)
        await self._async_save()
        await self._async_rebuild()

    async def async_set_mode(self, switch_id: str, mode: str) -> None:
        await self.async_save_switch({"id": self._switch(switch_id).id, "mode": mode})

    async def async_set_binding(
        self, switch_id: str, control: str, gesture: str, binding: dict | None, *, admin: bool
    ) -> None:
        """Set or clear one button's gesture. Non-admins may only use the menu."""
        switch = self._switch(switch_id)
        model = self._model(switch.model)
        c = model.control(control)
        if c is None or gesture not in c.gestures:
            raise BlueprinterError("invalid", "That button can't do that")
        if switch.is_fixed(control, gesture):
            raise BlueprinterError("fixed", f"{c.name}: {label(gesture)} is handled outside Home Assistant")
        current = switch.binding(control, gesture)
        if not admin and current is not None and "actions" in current:
            raise BlueprinterError("unauthorized", "An administrator set this one by hand, so only an administrator can change it")
        if binding is not None:
            if not admin and set(binding) != {"menu"}:
                raise BlueprinterError("unauthorized", "Only an administrator can write actions by hand")
            try:
                binding = check_binding(binding)
            except SwitchError as err:
                raise BlueprinterError("invalid", str(err)) from err
            try:
                await self._async_compile(binding)
            except Exception as err:  # noqa: BLE001 - HA's validators raise several kinds; all mean "not valid"
                raise BlueprinterError("invalid_actions", str(err)) from err
            switch.bindings.setdefault(control, {})[gesture] = binding
        else:
            switch.bindings.get(control, {}).pop(gesture, None)
            if control in switch.bindings and not switch.bindings[control]:
                del switch.bindings[control]
        self._scripts.pop((switch.id, control, gesture), None)
        await self._async_save()
        self._signal()

    async def async_test(self, switch_id: str, control: str, gesture: str, steps: int = 1) -> dict[str, Any]:
        """Act as if the gesture happened (the page's test button, and the press action)."""
        switch = self._switch(switch_id)
        model = self._model(switch.model)
        c = model.control(control)
        if c is None or gesture not in c.gestures:
            raise BlueprinterError("invalid", "That button can't do that")
        return self.fire(switch, Gesture(control, gesture, max(1, int(steps))), "test")

    def automation_config(self, entity_id: str) -> dict[str, Any] | None:
        from homeassistant.components.automation import DATA_COMPONENT

        component = self.hass.data.get(DATA_COMPONENT)
        entity = component.get_entity(entity_id) if component else None
        return getattr(entity, "raw_config", None) if entity else None

    async def async_import(self, switch_id: str, automation_id: str) -> list[str]:
        """Copy an old KNX "Wall buttons" automation's buttons onto the switch (admins).

        Simple actions become menu choices, so anyone can change them later.
        Gestures that are fixed on the switch are skipped.
        """
        switch = self._switch(switch_id)
        model = self._model(switch.model)
        if model.input != "knx":
            raise BlueprinterError("invalid", "Only KNX automations can be read so far")
        config = self.automation_config(automation_id)
        if not config:
            raise BlueprinterError("unknown_automation", "That automation wasn't found, or has no stored settings")
        read, notes = knx_addr.read_automation(model, switch.knx, config)
        bindings = {c: dict(g) for c, g in switch.bindings.items()}
        count = 0
        for control, gestures in read.items():
            for gesture, actions in gestures.items():
                if switch.is_fixed(control, gesture):
                    notes.append(f"{control} {label(gesture)} is fixed here, so it was skipped")
                    continue
                menu = from_actions(actions)
                bindings.setdefault(control, {})[gesture] = {"menu": menu} if menu else {"actions": actions}
                count += 1
        await self.async_save_switch({"id": switch.id, "bindings": bindings})
        return [f"{count} button gestures copied", *notes]

    async def async_apply_looks(self, by_address: dict[str, dict[str, dict]]) -> dict[str, list[str]]:
        """Looks per KNX plate address (from tools/ets_looks.py), onto the matching switches (admins).

        This is what the plates show now. Each switch's looks are replaced for the
        buttons given; others are kept. A wanted look the plate now shows is done.
        """
        applied: list[str] = []
        done: list[str] = []
        unmatched = sorted(by_address)
        for switch in list(self.switches.values()):
            address = switch.knx.get("address")
            if address not in by_address:
                continue
            unmatched.remove(address)
            model = self._model(switch.model)
            looks = {c: dict(v) for c, v in switch.looks.items()}
            looks.update({c: dict(v) for c, v in by_address[address].items()})
            wanted = {}
            for control, request in switch.wanted.items():
                if same_look(model, looks.get(control), request.get("look")):
                    done.append(f"{switch.name} · {self._control_name(model, control)}")
                else:
                    wanted[control] = request
            await self.async_save_switch({"id": switch.id, "looks": looks, "wanted": wanted})
            applied.append(switch.name)
        return {"applied": applied, "done": done, "no_switch": unmatched}

    @staticmethod
    def _control_name(model: Model, control: str) -> str:
        c = model.control(control)
        return c.name if c else control

    async def async_request_look(self, switch_id: str, control: str, look: dict | None, by: str) -> str:
        """Ask for a look that only ETS or a new insert can give (anyone). None withdraws it.

        Returns 'asked', 'withdrawn' or 'already' (the plate shows it already).
        """
        switch = self._switch(switch_id)
        model = self._model(switch.model)
        if model.control(control) is None:
            raise BlueprinterError("invalid", "That switch has no such button")
        if changed_where(model) is None:
            raise BlueprinterError("invalid", "This switch's looks are set here directly")
        if look is not None and changed_where(model) == "insert":
            # An insert's note is for this page only, so it changes straight away.
            plate = dict(switch.looks.get(control) or {})
            if look.get("label"):
                plate["label"] = look["label"]
            else:
                plate.pop("label", None)
            if plate:
                switch.looks[control] = plate
            else:
                switch.looks.pop(control, None)
        if look is None or same_look(model, switch.looks.get(control), look):
            switch.wanted.pop(control, None)
            await self._async_save()
            self._signal()
            return "withdrawn" if look is None else "already"
        look = full_look(model, look)
        try:
            check_looks({control: look}, model, self.icon_sets)
        except SwitchError as err:
            raise BlueprinterError("invalid", str(err)) from err
        if (switch.wanted.get(control) or {}).get("look") == look:
            return "asked"  # the same request again: keep it as it is, "In ETS" mark included
        switch.wanted[control] = {"look": look, "by": by, "at": dt_util.utcnow().isoformat()}
        await self._async_save()
        self._signal()
        return "asked"

    async def async_finish_request(self, switch_id: str, control: str) -> None:
        """An administrator says the plate now shows the wanted look (an insert, or an ETS change)."""
        switch = self._switch(switch_id)
        request = switch.wanted.get(control)
        if request is None:
            raise BlueprinterError("invalid", "Nothing is waiting on that button")
        looks = {c: dict(v) for c, v in switch.looks.items()}
        looks[control] = dict(request["look"])
        wanted = {c: v for c, v in switch.wanted.items() if c != control}
        await self.async_save_switch({"id": switch.id, "looks": looks, "wanted": wanted})

    async def async_mark_in_ets(self, switch_id: str, control: str, in_ets: bool, by: str) -> None:
        """An administrator has set the wanted look in ETS but not downloaded it yet (or takes that back).

        Only a note for keeping track: the request still waits until the plate shows it.
        """
        switch = self._switch(switch_id)
        request = switch.wanted.get(control)
        if request is None:
            raise BlueprinterError("invalid", "Nothing is waiting on that button")
        if in_ets:
            request["in_ets"] = {"by": by, "at": dt_util.utcnow().isoformat()}
        else:
            request.pop("in_ets", None)
        await self._async_save()
        self._signal()

    async def async_finish_in_ets(self, switch_id: str) -> int:
        """The plate has been downloaded: every request marked "In ETS" is done. Returns how many."""
        switch = self._switch(switch_id)
        done = [c for c, r in switch.wanted.items() if r.get("in_ets")]
        if not done:
            raise BlueprinterError("invalid", "Nothing on this switch is marked as in ETS")
        looks = {c: dict(v) for c, v in switch.looks.items()}
        for control in done:
            looks[control] = dict(switch.wanted[control]["look"])
        wanted = {c: v for c, v in switch.wanted.items() if c not in done}
        await self.async_save_switch({"id": switch.id, "looks": looks, "wanted": wanted})
        return len(done)

    def export(self, switch_id: str) -> dict[str, Any]:
        switch = self._switch(switch_id)
        return to_automation(switch, self._model(switch.model), self.z2m_topic(switch.device))

    def suggest_entities(self, model_id: str, device_id: str) -> dict[str, str]:
        """A device's event entities, matched to the model's slots."""
        model = self._model(model_id)
        ents = [
            e.entity_id
            for e in er.async_entries_for_device(er.async_get(self.hass), device_id)
            if e.domain == "event" and not e.disabled_by
        ]
        out: dict[str, str] = {}
        for slot in model.slots:
            match = next((e for e in sorted(ents) if slot.matches(e) and e not in out.values()), None)
            if match:
                out[slot.slot] = match
        return out

    # ---- the page's view --------------------------------------------------------------

    def snapshot(self, is_admin: bool) -> dict[str, Any]:
        areas = ar.async_get(self.hass)
        switches = []
        for switch in self.switches.values():
            model = self.models.get(switch.model)
            item = switch.as_dict()
            item["problems"] = []
            item["addresses"] = {}
            item["leds_now"] = {}
            if model is None:
                item["problems"].append("Its model file is missing")
            elif model.input == "knx":
                try:
                    for address, (control, channel) in knx_addr.addresses(model, switch.knx).items():
                        item["addresses"].setdefault(control, {})[channel] = address
                    for control, address in knx_addr.led_addresses(model, switch.knx).items():
                        item["addresses"].setdefault(control, {})["led"] = address
                except knx_addr.AddressError as err:
                    item["problems"].append(str(err))
                item["leds_now"] = {c: self.led_state(switch, c) for c in switch.leds}
            elif model.input == "zigbee2mqtt":
                if not switch.device:
                    item["problems"].append("No Zigbee2MQTT device chosen")
                elif self.z2m_topic(switch.device) is None:
                    item["problems"].append("Its device no longer exists")
            else:
                for slot in model.slots:
                    entity_id = switch.entities.get(slot.slot)
                    if not entity_id:
                        item["problems"].append(f"No entity for {slot.name}")
                    elif self.hass.states.get(entity_id) is None:
                        item["problems"].append(f"{entity_id} doesn't exist")
            play = self._plays.get(switch.id)
            item["put_back_until"] = play["until"] if play else None
            item["put_back_lights"] = [self._entity_name(e) for e in play["lights"]] if play else []
            item["waiting"] = {}
            if model is not None:
                icon_set = self.icon_sets.get(model.icon_set) if model.icon_set else None
                for control, request in switch.wanted.items():
                    item["waiting"][control] = {
                        **look_steps(model, control, switch.looks.get(control), request.get("look") or {}, icon_set),
                        "button": self._control_name(model, control),
                    }
            switches.append(item)
        return {
            "is_admin": is_admin,
            "models": [m.as_dict() for m in self.models.values()],
            "icon_sets": {k: v.as_dict() for k, v in self.icon_sets.items()},
            "icon_files": self.icon_files,
            "model_errors": self.model_errors,
            "gestures": GESTURES,
            "menu": {k: {"label": v[0], "fields": {f: list(r) for f, r in v[1].items()}} for k, v in MENU.items()},
            "areas": [{"id": a.id, "name": a.name, "floor": a.floor_id} for a in areas.async_list_areas()],
            "switches": switches,
            "log": list(self.log)[-150:],
            "knx": self.knx_state,
            "mqtt": self.mqtt_state,
            "z2m_devices": self._z2m_devices() if is_admin else [],
        }

    def _z2m_devices(self) -> list[dict[str, Any]]:
        """Zigbee2MQTT's devices (not its bridge), for choosing a zigbee2mqtt switch's device."""
        out = []
        for device in dr.async_get(self.hass).devices:  # iterating gives the entries (HA 2026.9+)
            ids = [i for d, i in device.identifiers if d == "mqtt" and i.startswith("zigbee2mqtt_")]
            if not ids or ids[0].startswith("zigbee2mqtt_bridge_"):
                continue
            out.append(
                {
                    "id": device.id,
                    "name": device.name_by_user or device.name or ids[0],
                    "model_id": device.model_id or "",
                    "model": f"{device.manufacturer or ''} {device.model or ''}".strip(),
                    "area_id": device.area_id,
                }
            )
        return sorted(out, key=lambda d: d["name"].lower())


def _knx_log(level: int, msg: str, **kwargs: Any) -> None:
    """HA's trigger helpers call this as log_cb(level, message)."""
    _LOGGER.log(level, msg, **kwargs)

