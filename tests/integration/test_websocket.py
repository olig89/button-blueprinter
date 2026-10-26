from __future__ import annotations

from custom_components.button_blueprinter.const import VERSION


async def test_subscribe_and_admin_gate(house, hass_ws_client, hass, hass_read_only_access_token):
    admin = await hass_ws_client(hass)
    await admin.send_json_auto_id({"type": "button_blueprinter/subscribe"})
    assert (await admin.receive_json())["success"]
    first = await admin.receive_json()
    assert first["event"]["version"] == VERSION and first["event"]["is_admin"] is True

    await admin.send_json_auto_id(
        {
            "type": "button_blueprinter/save_switch",
            "switch": {"name": "Small Bathroom", "model": "schneider_mtn6185", "knx": {"tap": "6/0/40", "hold": "6/1/40"}},
        }
    )
    while (msg := await admin.receive_json())["type"] != "result":
        pass
    assert msg["success"], msg

    user = await hass_ws_client(hass, hass_read_only_access_token)
    await user.send_json_auto_id(
        {"type": "button_blueprinter/save_switch", "switch": {"name": "X", "model": "schneider_mtn6185", "knx": {"tap": "6/0/1"}}}
    )
    msg = await user.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "unauthorized"

    await user.send_json_auto_id(
        {
            "type": "button_blueprinter/set_binding",
            "switch": "small_bathroom",
            "control": "b1",
            "gesture": "press",
            "binding": {"actions": [{"action": "light.toggle"}]},
        }
    )
    msg = await user.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "unauthorized"

    await user.send_json_auto_id(
        {
            "type": "button_blueprinter/set_binding",
            "switch": "small_bathroom",
            "control": "b1",
            "gesture": "press",
            "binding": {"menu": {"kind": "toggle", "entities": ["light.small_bathroom_mirror"]}},
        }
    )
    msg = await user.receive_json()
    assert msg["success"], msg
    assert house.bp.switches["small_bathroom"].binding("b1", "press")["menu"]["entities"] == ["light.small_bathroom_mirror"]


async def test_anyone_may_ask_for_a_look_but_only_admins_finish(house, hass_ws_client, hass, hass_read_only_access_token):
    await house.bp.async_save_switch(
        {"name": "Small Bathroom", "model": "schneider_mtn6185", "knx": {"tap": "6/0/40", "hold": "6/1/40"}}
    )
    user = await hass_ws_client(hass, hass_read_only_access_token)
    await user.send_json_auto_id(
        {"type": "button_blueprinter/request_look", "switch": "small_bathroom", "control": "b1", "look": {"icon": "bulb_on"}}
    )
    msg = await user.receive_json()
    assert msg["success"] and msg["result"]["result"] == "asked", msg
    await user.send_json_auto_id({"type": "button_blueprinter/finish_request", "switch": "small_bathroom", "control": "b1"})
    msg = await user.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "unauthorized"
    admin = await hass_ws_client(hass)
    await admin.send_json_auto_id({"type": "button_blueprinter/finish_request", "switch": "small_bathroom", "control": "b1"})
    msg = await admin.receive_json()
    assert msg["success"], msg
    assert house.bp.switches["small_bathroom"].looks["b1"]["icon"] == "bulb_on"


async def test_a_vacuum_binding_is_a_valid_home_assistant_script(house, hass_ws_client, hass, hass_read_only_access_token):
    menu = {"kind": "vacuum", "vacuum": "vacuum.robot", "area": "kitchen", "mode": "vac_and_mop"}
    compiled = await house.bp._async_compile({"menu": menu})
    assert compiled[0]["then"][0]["action"] == "vacuum.return_to_base"

    admin = await hass_ws_client(hass)
    await admin.send_json_auto_id(
        {
            "type": "button_blueprinter/save_switch",
            "switch": {"name": "Kitchen", "model": "schneider_mtn6185", "knx": {"tap": "6/0/24", "hold": "6/1/24"}},
        }
    )
    assert (await admin.receive_json())["success"]
    # A menu choice, so Alex (not an admin) may set it.
    user = await hass_ws_client(hass, hass_read_only_access_token)
    await user.send_json_auto_id(
        {"type": "button_blueprinter/set_binding", "switch": "kitchen", "control": "b4", "gesture": "long_press", "binding": {"menu": menu}}
    )
    msg = await user.receive_json()
    assert msg["success"], msg
    assert house.bp.switches["kitchen"].binding("b4", "long_press") == {"menu": menu}


async def test_in_ets_marks_requests_and_a_download_ticks_off_only_those(house, hass_ws_client, hass, hass_read_only_access_token):
    await house.bp.async_save_switch({"name": "Office", "model": "schneider_mtn619x", "knx": {"tap": "6/0/60", "hold": "6/1/60"}})
    admin = await hass_ws_client(hass)

    async def send(**msg):
        await admin.send_json_auto_id(msg)
        while (reply := await admin.receive_json())["type"] != "result":
            pass
        return reply

    for control, icon in (("b1", "bulb_on"), ("b3", "night"), ("b5", "dimming")):
        reply = await send(type="button_blueprinter/request_look", switch="office", control=control, look={"icon_off": icon})
        assert reply["success"], reply
    assert (await send(type="button_blueprinter/finish_in_ets", switch="office"))["success"] is False  # nothing marked yet

    for control in ("b1", "b3"):
        assert (await send(type="button_blueprinter/mark_in_ets", switch="office", control=control, in_ets=True))["success"]
    wanted = house.bp.switches["office"].wanted
    assert wanted["b1"]["in_ets"]["at"] and "in_ets" not in wanted["b5"]

    # Asking for the same look again keeps the mark; taking the mark back removes it.
    await send(type="button_blueprinter/request_look", switch="office", control="b3", look={"icon_off": "night"})
    assert "in_ets" in house.bp.switches["office"].wanted["b3"]
    assert (await send(type="button_blueprinter/mark_in_ets", switch="office", control="b3", in_ets=False))["success"]
    assert "in_ets" not in house.bp.switches["office"].wanted["b3"]
    assert (await send(type="button_blueprinter/mark_in_ets", switch="office", control="b7", in_ets=True))["success"] is False

    user = await hass_ws_client(hass, hass_read_only_access_token)
    await user.send_json_auto_id({"type": "button_blueprinter/mark_in_ets", "switch": "office", "control": "b5", "in_ets": True})
    msg = await user.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "unauthorized"

    reply = await send(type="button_blueprinter/finish_in_ets", switch="office")
    assert reply["success"] and reply["result"] == {"done": 1}, reply
    office = house.bp.switches["office"]
    assert office.looks["b1"]["icon_off"] == "bulb_on"
    assert set(office.wanted) == {"b3", "b5"}
