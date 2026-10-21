"""The page's websocket API.

Anyone signed in may watch, test a button, set a button from the menu, put a
switch's lights back now, and ask for a look that only ETS or a new insert can give.
Everything else (adding and changing switches, free-form actions, modes,
importing, exporting) is for administrators, enforced here, not only on the page.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .blueprinter import Blueprinter, BlueprinterError
from .const import DOMAIN, SIGNAL_CHANGED, VERSION


def _blueprinter(hass: HomeAssistant) -> Blueprinter | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        bp = getattr(entry, "runtime_data", None)
        if isinstance(bp, Blueprinter):
            return bp
    return None


def _ready(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> Blueprinter | None:
    bp = _blueprinter(hass)
    if bp is None:
        connection.send_error(msg["id"], "not_set_up", "Button Blueprinter isn't set up")
    return bp


def _admin(connection: websocket_api.ActiveConnection, msg: dict) -> bool:
    if connection.user.is_admin:
        return True
    connection.send_error(msg["id"], "unauthorized", "Only an administrator can change this")
    return False


async def _run(connection, msg, coro) -> None:
    try:
        result = await coro
    except BlueprinterError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result if isinstance(result, dict) else {"result": result})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    is_admin = connection.user.is_admin

    @callback
    def _send() -> None:
        bp = _blueprinter(hass)
        payload: dict[str, Any] = {"version": VERSION}
        payload.update(bp.snapshot(is_admin) if bp else {"error": "not_set_up"})
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_CHANGED, _send)
    connection.send_result(msg["id"])
    _send()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_binding",
        vol.Required("switch"): str,
        vol.Required("control"): str,
        vol.Required("gesture"): str,
        vol.Optional("binding"): vol.Any(None, dict),
    }
)
@websocket_api.async_response
async def ws_set_binding(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if bp := _ready(hass, connection, msg):
        await _run(
            connection,
            msg,
            bp.async_set_binding(
                msg["switch"], msg["control"], msg["gesture"], msg.get("binding"), admin=connection.user.is_admin
            ),
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/test",
        vol.Required("switch"): str,
        vol.Required("control"): str,
        vol.Required("gesture"): str,
        vol.Optional("steps", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)
@websocket_api.async_response
async def ws_test(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if bp := _ready(hass, connection, msg):
        await _run(connection, msg, bp.async_test(msg["switch"], msg["control"], msg["gesture"], msg["steps"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/put_back", vol.Required("switch"): str})
@websocket_api.async_response
async def ws_put_back(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Anyone may put a switch's lights back now (as a "put things back" button could)."""
    if bp := _ready(hass, connection, msg):
        await _run(connection, msg, bp.async_put_back(msg["switch"], "asked"))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/save_switch", vol.Required("switch"): dict}
)
@websocket_api.async_response
async def ws_save_switch(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):

        async def save() -> dict:
            return (await bp.async_save_switch(msg["switch"])).as_dict()

        await _run(connection, msg, save())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/delete_switch", vol.Required("switch"): str}
)
@websocket_api.async_response
async def ws_delete_switch(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):
        await _run(connection, msg, bp.async_delete_switch(msg["switch"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_mode",
        vol.Required("switch"): str,
        vol.Required("mode"): vol.In(["live", "dry_run", "off"]),
    }
)
@websocket_api.async_response
async def ws_set_mode(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):
        await _run(connection, msg, bp.async_set_mode(msg["switch"], msg["mode"]))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/import", vol.Required("switch"): str, vol.Required("automation"): str}
)
@websocket_api.async_response
async def ws_import(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):

        async def run() -> dict:
            return {"notes": await bp.async_import(msg["switch"], msg["automation"])}

        await _run(connection, msg, run())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/request_look",
        vol.Required("switch"): str,
        vol.Required("control"): str,
        vol.Optional("look"): vol.Any(None, {str: str}),
    }
)
@websocket_api.async_response
async def ws_request_look(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if bp := _ready(hass, connection, msg):
        by = connection.user.name or "Someone"

        async def run() -> dict:
            return {"result": await bp.async_request_look(msg["switch"], msg["control"], msg.get("look"), by)}

        await _run(connection, msg, run())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/finish_request", vol.Required("switch"): str, vol.Required("control"): str}
)
@websocket_api.async_response
async def ws_finish_request(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):
        await _run(connection, msg, bp.async_finish_request(msg["switch"], msg["control"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/mark_in_ets",
        vol.Required("switch"): str,
        vol.Required("control"): str,
        vol.Required("in_ets"): bool,
    }
)
@websocket_api.async_response
async def ws_mark_in_ets(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):
        by = connection.user.name or "Someone"
        await _run(connection, msg, bp.async_mark_in_ets(msg["switch"], msg["control"], msg["in_ets"], by))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/finish_in_ets", vol.Required("switch"): str})
@websocket_api.async_response
async def ws_finish_in_ets(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):

        async def run() -> dict:
            return {"done": await bp.async_finish_in_ets(msg["switch"])}

        await _run(connection, msg, run())


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/apply_looks", vol.Required("looks"): dict})
@websocket_api.async_response
async def ws_apply_looks(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):
        await _run(connection, msg, bp.async_apply_looks(msg["looks"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/export", vol.Required("switch"): str})
@websocket_api.async_response
async def ws_export(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):

        async def run() -> dict:
            return {"automation": bp.export(msg["switch"])}

        await _run(connection, msg, run())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/suggest", vol.Required("model"): str, vol.Required("device"): str}
)
@websocket_api.async_response
async def ws_suggest(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (bp := _ready(hass, connection, msg)) and _admin(connection, msg):

        async def run() -> dict:
            return {"entities": bp.suggest_entities(msg["model"], msg["device"])}

        await _run(connection, msg, run())


def async_register_websocket(hass: HomeAssistant) -> None:
    for handler in (
        ws_subscribe,
        ws_set_binding,
        ws_test,
        ws_put_back,
        ws_save_switch,
        ws_delete_switch,
        ws_set_mode,
        ws_import,
        ws_request_look,
        ws_finish_request,
        ws_mark_in_ets,
        ws_finish_in_ets,
        ws_apply_looks,
        ws_export,
        ws_suggest,
    ):
        websocket_api.async_register_command(hass, handler)
