from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.button_blueprinter.blueprinter import BlueprinterError

SMALL = {"tap": "6/0/40", "hold": "6/1/40", "led": "6/2/40", "address": "1.1.31"}
FIXED = {"b2": {"long_press": "Room lights on (KNX)"}, "b4": {"long_press": "Room lights off (KNX)"}}


async def small_bathroom(house, **extra):
    return await house.bp.async_save_switch(
        {"name": "Small Bathroom", "model": "schneider_mtn6185", "area_id": "small_bathroom", "knx": SMALL, "fixed": FIXED, **extra}
    )


async def test_models_load(house):
    assert {"schneider_mtn619x", "schneider_mtn6185", "hue_dimmer", "hue_tap_dial", "senic_nuimo"} <= set(house.bp.models)
    assert house.bp.model_errors == []


async def test_a_new_switch_starts_in_dry_run_and_logs(house):
    switch = await small_bathroom(
        house, bindings={"b1": {"press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}}}
    )
    assert switch.mode == "dry_run"
    house.bp.handle_telegram("6/0/40", "GroupValueWrite")
    await house.hass.async_block_till_done()
    assert house.services("light") == []
    assert house.bp.log[-1]["result"] == "would run"
    assert house.bp.log[-1]["control"] == "b1"


async def test_live_runs_and_reads_ignore_inputs(house):
    await small_bathroom(
        house,
        mode="live",
        bindings={
            "b1": {
                "press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}},
                "long_press": {"menu": {"kind": "turn_on", "entities": ["light.small_bathroom_ceiling"], "brightness": 100}},
            }
        },
    )
    house.bp.handle_telegram("6/0/40", "GroupValueRead")  # not a press
    house.bp.handle_telegram("6/0/40", "GroupValueWrite")
    house.bp.handle_telegram("6/1/40", "GroupValueWrite")
    await house.hass.async_block_till_done()
    assert house.services("light", "toggle") == [{"entity_id": ["light.small_bathroom_ceiling"]}]
    assert house.services("light", "turn_on")[0]["brightness_pct"] == 100


async def test_fixed_and_unset(house):
    await small_bathroom(house, mode="live")
    house.bp.handle_telegram("6/0/43", "GroupValueWrite")
    await house.hass.async_block_till_done()
    assert house.bp.log[-1]["result"] == "nothing set"
    entry = await house.bp.async_test("small_bathroom", "b2", "long_press")
    assert entry["result"] == "fixed" and "KNX" in entry["detail"]


async def test_import_the_old_automation(house):
    await small_bathroom(house)
    notes = await house.bp.async_import("small_bathroom", "automation.wall_buttons_small_bathroom_1_1_31")
    assert notes[0] == "3 button gestures copied"
    switch = house.bp.switches["small_bathroom"]
    assert switch.binding("b1", "press") == {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}
    assert switch.binding("b1", "long_press")["menu"]["brightness"] == 100
    assert switch.binding("b2", "press")["menu"]["kind"] == "toggle"


async def test_two_switches_cant_share_an_address(house):
    await small_bathroom(house)
    with pytest.raises(BlueprinterError, match="already used"):
        await house.bp.async_save_switch({"name": "Copy", "model": "schneider_mtn6185", "knx": SMALL})


async def test_bad_actions_are_refused_at_save(house):
    with pytest.raises(BlueprinterError):
        await small_bathroom(house, bindings={"b1": {"press": {"actions": [{"not_an_action": 1}]}}})


async def test_non_admins_only_use_the_menu(house):
    await small_bathroom(house)
    with pytest.raises(BlueprinterError, match="administrator"):
        await house.bp.async_set_binding("small_bathroom", "b1", "press", {"actions": [{"action": "light.toggle"}]}, admin=False)
    await house.bp.async_set_binding(
        "small_bathroom", "b1", "press", {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_mirror"]}}, admin=False
    )
    await house.bp.async_set_binding("small_bathroom", "b3", "press", {"actions": [{"action": "light.toggle", "target": {"entity_id": "light.x"}}]}, admin=True)
    with pytest.raises(BlueprinterError, match="by hand"):
        await house.bp.async_set_binding("small_bathroom", "b3", "press", None, admin=False)
    with pytest.raises(BlueprinterError, match="outside"):
        await house.bp.async_set_binding(
            "small_bathroom", "b2", "long_press", {"menu": {"kind": "toggle", "entities": ["light.x"]}}, admin=True
        )


async def test_leds_follow_their_entity_and_answer_reads(house, hass: HomeAssistant):
    await small_bathroom(house, mode="live", leds={"b1": {"entity_id": "binary_sensor.office_bright_active"}})
    hass.states.async_set("binary_sensor.office_bright_active", "on")
    await hass.async_block_till_done()
    assert house.services("knx", "send")[-1] == {"address": "6/2/40", "payload": 1}
    house.bp.handle_telegram("6/2/40", "GroupValueRead")
    await hass.async_block_till_done()
    assert house.services("knx", "send")[-1] == {"address": "6/2/40", "payload": 1, "response": True}


async def test_leds_stay_quiet_in_a_dry_run(house, hass: HomeAssistant):
    await small_bathroom(house, leds={"b1": {"entity_id": "binary_sensor.office_bright_active"}})
    hass.states.async_set("binary_sensor.office_bright_active", "on")
    house.bp.handle_telegram("6/2/40", "GroupValueRead")
    await hass.async_block_till_done()
    assert house.services("knx") == []


async def dimmer(house, **extra):
    return await house.bp.async_save_switch(
        {
            "name": "Office Dimmer",
            "model": "hue_dimmer",
            "mode": "live",
            "entities": {f"button_{i}": f"event.office_dimmer_button_{i}" for i in range(1, 5)},
            **extra,
        }
    )


async def test_hue_tap_without_a_double_binding_runs_at_once(house):
    await dimmer(house, bindings={"top": {"press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}}})
    await house.press("event.office_dimmer_button_1", "initial_press")  # from "unknown": the first event counts
    await house.press("event.office_dimmer_button_1", "short_release")
    assert len(house.services("light", "toggle")) == 1


async def test_hue_double_tap_waits_then_decides(house, hass: HomeAssistant):
    await dimmer(
        house,
        bindings={
            "top": {
                "press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}},
                "double_press": {"menu": {"kind": "turn_off", "entities": ["light.small_bathroom_mirror"]}},
            }
        },
    )
    await house.press("event.office_dimmer_button_1", "short_release")
    assert house.services("light") == []
    await house.press("event.office_dimmer_button_1", "short_release")
    assert house.services("homeassistant", "turn_off") == [{"entity_id": ["light.small_bathroom_mirror"]}]
    # A single tap fires once the window has passed.
    await house.press("event.office_dimmer_button_1", "short_release")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert len(house.services("light", "toggle")) == 1


async def test_a_restored_state_is_not_a_press(house, hass: HomeAssistant):
    await dimmer(house, bindings={"top": {"press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}}})
    hass.states.async_set("event.office_dimmer_button_1", "unavailable")
    await hass.async_block_till_done()
    await house.press("event.office_dimmer_button_1", "short_release")  # back from unavailable
    assert house.services("light") == []


async def test_nuimo_hold_and_turns(house, hass: HomeAssistant):
    await house.bp.async_save_switch(
        {
            "name": "Nuimo",
            "model": "senic_nuimo",
            "mode": "live",
            "entities": {"control": "event.nuimo_control_button"},
            "bindings": {
                "ring": {"turn_right": {"menu": {"kind": "media", "entity": "media_player.office", "command": "volume_up"}}},
                "top": {"long_press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}},
            },
        }
    )
    await house.press("event.nuimo_control_button", "rotate", delta=31, direction="clockwise")
    assert len(house.services("media_player", "volume_up")) == 3
    await house.press("event.nuimo_control_button", "press")
    assert house.services("light") == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert len(house.services("light", "toggle")) == 1
    await house.press("event.nuimo_control_button", "release")
    assert house.bp.log[-1]["gesture"] == "long_press_release"


async def test_office_scene_again_turns_off(house, hass: HomeAssistant):
    hass.states.async_set("scene.office_bright", "2026-10-08T10:00:00+00:00", {"entity_id": ["light.small_bathroom_ceiling"]})
    hass.states.async_set("scene.office_dark", "2026-10-08T09:00:00+00:00", {"entity_id": ["light.small_bathroom_ceiling"]})
    await house.bp.async_save_switch(
        {
            "name": "Office",
            "model": "schneider_mtn619x",
            "mode": "live",
            "knx": {"tap": "6/0/60", "hold": "6/1/60", "led": "6/2/60"},
            "bindings": {
                "b1": {"press": {"menu": {"kind": "scene", "scene": "scene.office_bright", "again_off": True}}},
                "b5": {"press": {"menu": {"kind": "scene", "scene": "scene.office_dark", "again_off": True}}},
            },
        }
    )
    hass.states.async_set("light.small_bathroom_ceiling", "on")
    house.bp.handle_telegram("6/0/60", "GroupValueWrite")  # bright was used last and its light is on -> off
    await hass.async_block_till_done()
    assert house.services("homeassistant", "turn_off")[-1] == {"entity_id": ["light.small_bathroom_ceiling"]}
    house.bp.handle_telegram("6/0/64", "GroupValueWrite")  # dark wasn't last -> turn it on
    await hass.async_block_till_done()
    assert house.services("scene", "turn_on")[-1] == {"entity_id": ["scene.office_dark"]}


async def test_export_and_snapshot(house):
    await small_bathroom(house, bindings={"b1": {"press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}}})
    auto = house.bp.export("small_bathroom")
    assert auto["triggers"][0]["destination"] == ["6/0/40"]
    snap = house.bp.snapshot(is_admin=False)
    sw = snap["switches"][0]
    assert sw["addresses"]["b1"] == {"tap": "6/0/40", "hold": "6/1/40", "led": "6/2/40"}
    assert snap["is_admin"] is False and "toggle" in snap["menu"]


async def test_switches_survive_a_reload(house, hass: HomeAssistant):
    await small_bathroom(house)
    await hass.config_entries.async_reload(house.entry.entry_id)
    await hass.async_block_till_done()
    assert "small_bathroom" in house.entry.runtime_data.switches


async def test_knx_listener_gets_a_normalised_trigger(house, hass: HomeAssistant, monkeypatch):
    """The KNX trigger helpers need `platform:`, not `trigger:` (found on a real install, 2026-10-08)."""
    from custom_components.button_blueprinter import blueprinter as mod

    seen = {}

    async def fake_validate(hass_, config):
        seen["validated"] = config
        assert all("platform" in c and "trigger" not in c for c in config)
        return config

    async def fake_init(hass_, config, action, domain, name, log_cb, *args, **kwargs):
        seen["initialised"] = config
        log_cb(logging.INFO, "Initialized trigger")  # how HA's helper calls it
        return lambda: None

    monkeypatch.setattr(mod, "async_validate_trigger_config", fake_validate)
    monkeypatch.setattr(mod, "async_initialize_triggers", fake_init)
    hass.config.components.add("knx")
    await small_bathroom(house, leds={"b1": {"entity_id": "binary_sensor.office_bright_active"}})
    assert house.bp.knx_state == "listening"
    writes, reads = seen["initialised"]
    assert writes["platform"] == "knx.telegram" and "6/0/40" in writes["destination"]
    assert reads["group_value_write"] is False and reads["destination"] == ["6/2/40"]


async def test_real_knx_trigger_delivers_presses(house, hass: HomeAssistant):
    """No mocks: the KNX integration's own trigger code, fed a real telegram."""
    xknx = pytest.importorskip("xknx")
    del xknx
    from xknx.dpt import DPTBinary
    from xknx.telegram import GroupAddress, IndividualAddress, Telegram, TelegramDirection
    from xknx.telegram.apci import GroupValueRead, GroupValueWrite

    from homeassistant.components.knx.const import SIGNAL_KNX_TELEGRAM
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    hass.config.components.add("knx")
    await small_bathroom(
        house,
        mode="live",
        leds={"b1": {"entity_id": "binary_sensor.office_bright_active"}},
        bindings={"b1": {"press": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_ceiling"]}}}},
    )
    assert house.bp.knx_state == "listening"

    def send(address, payload, kind):
        telegram = Telegram(
            destination_address=GroupAddress(address),
            direction=TelegramDirection.INCOMING,
            payload=payload,
            source_address=IndividualAddress("1.1.31"),
        )
        async_dispatcher_send(
            hass, SIGNAL_KNX_TELEGRAM, telegram, {"destination": address, "telegramtype": kind, "direction": "Incoming"}
        )

    send("6/0/40", GroupValueWrite(DPTBinary(1)), "GroupValueWrite")
    await hass.async_block_till_done()
    assert house.services("light", "toggle") == [{"entity_id": ["light.small_bathroom_ceiling"]}]
    send("6/2/40", GroupValueRead(), "GroupValueRead")
    await hass.async_block_till_done()
    assert house.services("knx", "send")[-1]["response"] is True


async def test_apply_looks_by_plate_address(house):
    await small_bathroom(house)
    await house.bp.async_save_switch({"name": "Office", "model": "schneider_mtn619x", "knx": {"tap": "6/0/60", "led": "6/2/60", "address": "1.1.32"}})
    got = await house.bp.async_apply_looks(
        {
            "1.1.32": {"b3": {"label": "Button 3", "show": "icon", "icon_on": "working", "icon_off": "working", "colour_on": "green", "colour_off": "white"}},
            "1.1.99": {"b1": {"icon_on": "bulb_on"}},
        }
    )
    assert got == {"applied": ["Office"], "done": [], "no_switch": ["1.1.99"]}
    assert house.bp.switches["office"].looks["b3"]["icon_on"] == "working"
    with pytest.raises(BlueprinterError, match="isn't one of"):
        await house.bp.async_apply_looks({"1.1.32": {"b1": {"icon_on": "mdi:lightbulb"}}})
    snap = house.bp.snapshot(is_admin=True)
    assert "schneider_dlife" in snap["icon_sets"] and snap["icon_files"]["schneider_dlife"] == []


async def test_wanted_looks_wait_for_ets_and_clear_themselves(house):
    await house.bp.async_save_switch({"name": "Office", "model": "schneider_mtn619x", "knx": {"tap": "6/0/60", "led": "6/2/60", "address": "1.1.32"}})
    plate = {"label": "Button 3", "show": "icon", "icon_on": "working", "icon_off": "working", "colour_on": "green", "colour_off": "white"}
    await house.bp.async_apply_looks({"1.1.32": {"b3": plate}})
    wanted = {**plate, "label": "Dimmed", "show": "icon_name"}
    assert await house.bp.async_request_look("office", "b3", wanted, "Alex") == "asked"
    office = house.bp.switches["office"]
    assert office.looks["b3"]["label"] == "Button 3"  # the plate is unchanged
    assert office.wanted["b3"]["by"] == "Alex"
    item = next(s for s in house.bp.snapshot(is_admin=False)["switches"] if s["id"] == "office")
    assert item["waiting"]["b3"]["function"] == "Function 3"
    assert {c["setting"] for c in item["waiting"]["b3"]["changes"]} == {"Indication type", "Name of the channel"}
    # Asking for what the plate shows already is no request.
    assert await house.bp.async_request_look("office", "b1", {}, "Alex") == "already"
    assert "b1" not in office.wanted
    with pytest.raises(BlueprinterError, match="colours are"):
        await house.bp.async_request_look("office", "b3", {"colour_on": "purple"}, "Alex")
    # A fresh read of ETS that matches ticks it off.
    got = await house.bp.async_apply_looks({"1.1.32": {"b3": wanted}})
    assert got["done"] == ["Office · Button 3"]
    assert house.bp.switches["office"].wanted == {}


async def test_inserts_finish_by_hand_and_notes_save_at_once(house):
    await small_bathroom(house)
    assert await house.bp.async_request_look("small_bathroom", "b1", {"icon": "ceiling_lamp", "label": "ceiling"}, "Alex") == "asked"
    s = house.bp.switches["small_bathroom"]
    assert s.looks["b1"] == {"label": "ceiling"}  # the note is this page's own
    await house.bp.async_finish_request("small_bathroom", "b1")
    s = house.bp.switches["small_bathroom"]
    assert s.looks["b1"]["icon"] == "ceiling_lamp" and s.wanted == {}
    assert await house.bp.async_request_look("small_bathroom", "b3", {"icon": "message"}, "Alex") == "asked"
    assert await house.bp.async_request_look("small_bathroom", "b3", None, "Alex") == "withdrawn"
    assert house.bp.switches["small_bathroom"].wanted == {}
    with pytest.raises(BlueprinterError, match="Nothing is waiting"):
        await house.bp.async_finish_request("small_bathroom", "b3")


async def test_cube_faces_and_turns_from_zigbee2mqtt(house, hass: HomeAssistant, monkeypatch):
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    mqtt_entry = MockConfigEntry(domain="mqtt")
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_0x0011223344556677")},
        name="0x0011223344556677",
        manufacturer="Aqara",
        model="Cube T1 Pro",
        model_id="CTP-R01",
    )
    lamp = ["light.small_bathroom_ceiling"]
    switch = await house.bp.async_save_switch(
        {
            "name": "Cube",
            "model": "aqara_cube_t1_pro",
            "mode": "live",
            "device": device.id,
            "bindings": {
                "face_3": {"face_up": {"menu": {"kind": "colour", "entities": lamp, "colour": "yellow"}}},
                "rotate": {
                    "turn_right": {"menu": {"kind": "brighter", "entities": lamp}},
                    "turn_left": {"menu": {"kind": "dimmer", "entities": lamp}},
                },
            },
        }
    )
    assert house.bp.mqtt_state == "waiting for the MQTT integration"  # MQTT isn't loaded in the tests
    assert house.bp.export(switch.id)["triggers"][0]["topic"] == "zigbee2mqtt/0x0011223344556677"
    # Listing devices must not use the registry as a mapping (deprecated, breaks in HA 2027.9).
    view = type(dr.async_get(hass).devices)
    if hasattr(view, "_report_deprecated_use"):
        monkeypatch.setattr(view, "_report_deprecated_use", lambda self: pytest.fail("deprecated device registry use"))
    snap = house.bp.snapshot(is_admin=True)
    assert [d["model_id"] for d in snap["z2m_devices"]] == ["CTP-R01"]
    assert next(s for s in snap["switches"] if s["id"] == switch.id)["problems"] == []

    bp = house.bp
    bp.handle_z2m(device.id, {"battery": 100, "side": 3})  # a plain report: no action, no press
    bp.handle_z2m(device.id, {"action": "flip_to_side", "side": 3, "action_angle": None})
    bp.handle_z2m(device.id, {"action": "rotate_left", "action_angle": -61.7, "side": 3})
    bp.handle_z2m(device.id, {"action": "flip_to_side", "side": 5})  # no binding on face 5
    await hass.async_block_till_done()
    ons = house.services("light", "turn_on")
    assert ons[0]["rgb_color"] == [255, 210, 0]
    assert ons[1]["brightness_step_pct"] == -20
    assert len(ons) == 2
    assert [e["gesture"] for e in bp.log][-3:] == ["face_up", "turn_left", "face_up"]


async def lounge_cube(house, hass: HomeAssistant, **extra):
    """The cube on the small bathroom ceiling light, putting things back after 30 minutes."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    mqtt_entry = MockConfigEntry(domain="mqtt")
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0xcube")}, name="0xcube"
    )
    lamp = ["light.small_bathroom_ceiling"]
    switch = await house.bp.async_save_switch(
        {
            "name": "Cube",
            "model": "aqara_cube_t1_pro",
            "mode": "live",
            "device": device.id,
            "put_back": {"minutes": 30},
            "bindings": {
                "face_1": {"face_up": {"menu": {"kind": "colour", "entities": lamp, "colour": "red"}}},
                "rotate": {"turn_right": {"menu": {"kind": "brighter", "entities": lamp}}},
                "cube": {"shake": {"menu": {"kind": "put_back"}}},
            },
            **extra,
        }
    )
    return switch, device.id


WARM = {"brightness": 100, "color_mode": "color_temp", "color_temp_kelvin": 2700}


async def test_put_back_after_the_time_runs_out(house, hass: HomeAssistant):
    from homeassistant.core import Context

    hass.states.async_set("light.small_bathroom_ceiling", "on", WARM)
    switch, device = await lounge_cube(house, hass)
    house.bp.handle_z2m(device, {"action": "flip_to_side", "side": 1})
    await hass.async_block_till_done()
    play = house.bp._plays[switch.id]
    assert play["lights"] == {"light.small_bathroom_ceiling": {"state": "on", "brightness": 100, "color_temp_kelvin": 2700}}
    # The light turns red with the cube's own context: still the cube's.
    ours = next(iter(house.bp._play_contexts[switch.id]))
    hass.states.async_set("light.small_bathroom_ceiling", "on", {"brightness": 100, "color_mode": "xy", "xy_color": (0.7, 0.3)}, context=Context(id=ours))
    await hass.async_block_till_done()
    assert "light.small_bathroom_ceiling" in play["lights"]
    house.bp.handle_z2m(device, {"action": "rotate_right", "action_angle": 35})
    await hass.async_block_till_done()
    house.calls.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert house.services("light", "turn_on") == [{"entity_id": "light.small_bathroom_ceiling", "brightness": 100, "color_temp_kelvin": 2700}]
    assert switch.id not in house.bp._plays
    assert house.bp.log[-1]["result"] == "put back"


async def test_a_light_changed_another_way_is_left_alone(house, hass: HomeAssistant):
    hass.states.async_set("light.small_bathroom_ceiling", "off")
    switch, device = await lounge_cube(house, hass)
    house.bp.handle_z2m(device, {"action": "flip_to_side", "side": 1})
    await hass.async_block_till_done()
    assert house.bp._plays[switch.id]["lights"] == {"light.small_bathroom_ceiling": {"state": "off"}}
    hass.states.async_set("light.small_bathroom_ceiling", "on", WARM)  # someone at the wall
    await hass.async_block_till_done()
    assert switch.id not in house.bp._plays
    house.calls.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert house.services("light") == []


async def test_shake_puts_back_now_and_plays_are_stored(house, hass: HomeAssistant):
    hass.states.async_set("light.small_bathroom_ceiling", "off")
    switch, device = await lounge_cube(house, hass)
    house.bp.handle_z2m(device, {"action": "rotate_right", "action_angle": 35})
    await hass.async_block_till_done()
    assert house.bp._stored()["put_back"][switch.id]["lights"] == {"light.small_bathroom_ceiling": {"state": "off"}}
    snap = next(s for s in house.bp.snapshot(is_admin=False)["switches"] if s["id"] == switch.id)
    assert snap["put_back_until"] and snap["put_back_lights"] == ["light.small_bathroom_ceiling"]
    house.calls.clear()
    house.bp.handle_z2m(device, {"action": "shake"})
    await hass.async_block_till_done()
    assert house.services("light", "turn_off") == [{"entity_id": "light.small_bathroom_ceiling"}]
    assert switch.id not in house.bp._plays


async def test_only_the_chosen_buttons_are_for_now(house, hass: HomeAssistant):
    hass.states.async_set("light.small_bathroom_ceiling", "off")
    switch, device = await lounge_cube(house, hass, put_back={"minutes": 30, "controls": ["face_1"]})
    house.bp.handle_z2m(device, {"action": "rotate_right", "action_angle": 35})
    await hass.async_block_till_done()
    assert switch.id not in house.bp._plays
    with pytest.raises(BlueprinterError, match="putting lights back"):
        await house.bp.async_save_switch({"id": switch.id, "put_back": None})


async def test_each_press_starts_the_clock_again(house, hass: HomeAssistant, freezer):
    hass.states.async_set("light.small_bathroom_ceiling", "off")
    switch, device = await lounge_cube(house, hass)
    house.bp.handle_z2m(device, {"action": "rotate_right", "action_angle": 35})
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=20))
    house.bp.handle_z2m(device, {"action": "rotate_right", "action_angle": 35})
    await hass.async_block_till_done()
    house.calls.clear()
    freezer.tick(timedelta(minutes=15))  # 35 minutes after the first press, 15 after the last
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert house.services("light", "turn_off") == []
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert house.services("light", "turn_off") == [{"entity_id": "light.small_bathroom_ceiling"}]


async def test_turns_while_one_runs_are_added_up(house, hass: HomeAssistant):
    hass.states.async_set("light.small_bathroom_ceiling", "on", WARM)
    lamp = ["light.small_bathroom_ceiling"]
    switch, device = await lounge_cube(
        house,
        hass,
        bindings={
            "rotate": {
                "turn_right": {"menu": {"kind": "brighter", "entities": lamp}},
                "turn_left": {"menu": {"kind": "dimmer", "entities": lamp}},
            }
        },
    )
    # The light takes its time with the first command (as Hue does), while three more turns arrive:
    # those go as one net turn once the first is done.
    import asyncio

    held = asyncio.Event()
    sent: list[int] = []

    async def slow_turn_on(call) -> None:
        sent.append(call.data["brightness_step_pct"])
        await held.wait()

    hass.services.async_register("light", "turn_on", slow_turn_on)
    for angle, action in ((35, "rotate_right"), (65, "rotate_right"), (-95, "rotate_left"), (-60, "rotate_left")):
        house.bp.handle_z2m(device, {"action": action, "action_angle": angle})
        await asyncio.sleep(0)
    held.set()
    await hass.async_block_till_done()
    steps = sent
    assert steps == [10, -30]  # +1, then +2 -3 -2 = -3
    assert [e["gesture"] for e in house.bp.log][-4:] == ["turn_right", "turn_right", "turn_left", "turn_left"]
    assert house.bp._turning == {}
