"""Names shared by the Home Assistant side of Button Blueprinter."""

from __future__ import annotations

DOMAIN = "button_blueprinter"
NAME = "Button Blueprinter"
VERSION = "0.7.4"  # also manifest.json and www/button-blueprinter.js (a test checks)

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

PANEL_URL = "button-blueprinter"
PANEL_COMPONENT = "button-blueprinter-panel"
STATIC_URL = "/button_blueprinter_static"
ICON_URL = "/button_blueprinter_icons"  # the real switch icons, when installed
FRONTEND_FILE = "button-blueprinter.js"

SIGNAL_CHANGED = f"{DOMAIN}_changed"

Z2M_BASE_TOPIC = "zigbee2mqtt"  # Zigbee2MQTT's default base topic

LOG_SIZE = 300  # presses kept for the page (in memory)

SERVICE_PRESS = "press"
SERVICE_PUT_BACK = "put_back"
