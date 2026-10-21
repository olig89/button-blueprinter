"""Button Blueprinter: every switch in the house, room by room, and what each button does.

``blueprinter.py`` does the work; ``core/`` holds the rules with no Home
Assistant imports; ``models/`` has one file per switch model; the page is in
``www/``.
"""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .blueprinter import ICON_FILES_FOLDER, Blueprinter, BlueprinterError
from .const import DOMAIN, FRONTEND_FILE, ICON_URL, NAME, PANEL_COMPONENT, PANEL_URL, SERVICE_PRESS, SERVICE_PUT_BACK, STATIC_URL
from .websocket import _blueprinter, async_register_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type BlueprinterConfigEntry = ConfigEntry[Blueprinter]

PRESS_SCHEMA = vol.Schema(
    {
        vol.Required("switch"): cv.string,
        vol.Required("control"): cv.string,
        vol.Required("gesture"): cv.string,
        vol.Optional("steps", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)

PUT_BACK_SCHEMA = vol.Schema({vol.Required("switch"): cv.string})


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """The sidebar page. Skipped quietly where the frontend isn't loaded (tests)."""
    if hass.data.get(f"{DOMAIN}_frontend") or "frontend" not in hass.config.components:
        return
    from homeassistant.components import panel_custom
    from homeassistant.components.http import StaticPathConfig

    www = Path(__file__).parent / "www"
    paths = [StaticPathConfig(STATIC_URL, str(www), False)]
    # The real switch icons, if they have been copied into HA (tools/schneider_icons.py).
    icons = Path(hass.config.path(ICON_FILES_FOLDER))
    if await hass.async_add_executor_job(icons.is_dir):
        paths.append(StaticPathConfig(ICON_URL, str(icons), True))
    await hass.http.async_register_static_paths(paths)
    version = (await hass.async_add_executor_job((www / FRONTEND_FILE).stat)).st_mtime_ns
    url = f"{STATIC_URL}/{FRONTEND_FILE}?v={version}"
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=NAME,
        sidebar_icon="mdi:gesture-tap-button",
        module_url=url,
        # Everyone can see the switches and set a button from the menu; the
        # server refuses everything else to non-admins.
        require_admin=False,
    )
    hass.data[f"{DOMAIN}_frontend"] = url


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_websocket(hass)

    async def press(call: ServiceCall) -> ServiceResponse:
        bp = _blueprinter(hass)
        if bp is None:
            raise ServiceValidationError("Button Blueprinter isn't set up")
        try:
            return await bp.async_test(call.data["switch"], call.data["control"], call.data["gesture"], call.data["steps"])
        except BlueprinterError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_PRESS, press, schema=PRESS_SCHEMA, supports_response=SupportsResponse.OPTIONAL)

    async def put_back(call: ServiceCall) -> ServiceResponse:
        bp = _blueprinter(hass)
        if bp is None:
            raise ServiceValidationError("Button Blueprinter isn't set up")
        if call.data["switch"] not in bp.switches:
            raise ServiceValidationError(f"No switch '{call.data['switch']}'")
        return await bp.async_put_back(call.data["switch"], "asked")

    hass.services.async_register(
        DOMAIN, SERVICE_PUT_BACK, put_back, schema=PUT_BACK_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BlueprinterConfigEntry) -> bool:
    entry.runtime_data = Blueprinter(hass, entry)
    await entry.runtime_data.async_start()
    await _async_register_frontend(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlueprinterConfigEntry) -> bool:
    await entry.runtime_data.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BlueprinterConfigEntry) -> None:
    if hass.data.pop(f"{DOMAIN}_frontend", None):
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, PANEL_URL)
