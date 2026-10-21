"""Button Blueprinter's rules, with no Home Assistant imports (CI checks this).

- ``gestures``: the words for what you do to a control.
- ``models``: switch models, loaded from one YAML file each.
- ``switches``: a switch in a room, its bindings, looks and fixed controls.
- ``timing``: tap, double press and hold made from raw presses.
- ``translate``: a device's own events turned into gestures.
- ``palette``: the menu of safe actions, and the HA actions each one runs.
- ``knx``: group addresses, and reading the old wall-button automations.
- ``export``: a switch's bindings as a plain automation.
"""
