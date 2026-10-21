"""Each D-Life Dynamics plate's button looks, as ETS has them: name, what it
shows, and the icon and colour for status on and off.

Inputs:
- a JSON export of the project's parameter values (knx-params.json), shaped
  {"<device address>": {"parameters": {"<parameter ref id>": {"value": ...}}}}:
  the values ETS has set on each device (the ref ids as in the project's
  0.xml, for example read with xknxproject);
- the .knxproj itself, only for Schneider's application file (unencrypted),
  which says which setting belongs to which button and what the defaults are.

Usage:

    python tools/ets_looks.py knx-params.json MyHouse.knxproj > looks.json

Prints {"1.1.32": {"b1": {...}, ...}, ...} for every device that runs the
"Push Button Dynamic Labelling" application (app 1871). Apply it with the
admin websocket command `button_blueprinter/apply_looks` ({"looks": <that>}).
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1] / "custom_components" / "button_blueprinter"
APP = re.compile(r"^M-0064/M-0064_A-1871-[^/]+\.xml$")
FIELDS = {
    "Name of the channel": "label",
    "Indication type": "show",
    "Icon for status on": "icon_on",
    "Icon for status off": "icon_off",
    "Colour for status on": "colour_on",
    "Colour for status off": "colour_off",
}
SHOW = {"1": "icon", "2": "icon_name", "3": "none"}
COLOURS = {"0": "white", "1": "green", "2": "blue", "3": "red", "4": "orange", "5": "yellow"}


def app_layout(project: str) -> tuple[dict[str, tuple[int, str]], dict[str, str]]:
    """Parameter ref (e.g. 'P-90_R-91') -> (function number, look field); field defaults by ref."""
    with zipfile.ZipFile(project) as z:
        name = next((n for n in z.namelist() if APP.match(n)), None)
        if name is None:
            raise SystemExit("No Schneider app 1871 (Push Button Dynamic Labelling) in this project")
        root = ET.fromstring(z.read(name))
    ns = "{" + root.tag.split("}")[0][1:] + "}"
    prefix = name.split("/")[-1][:-4] + "_"
    params = {p.get("Id"): p for p in root.iter(ns + "Parameter")}
    refs = {r.get("Id"): r for r in root.iter(ns + "ParameterRef")}
    parent = {c: p for p in root.iter() for c in p}
    layout: dict[str, tuple[int, str]] = {}
    defaults: dict[str, str] = {}
    for rr in root.iter(ns + "ParameterRefRef"):
        ref = refs.get(rr.get("RefId"))
        if ref is None:
            continue
        param = params.get(ref.get("RefId"))
        field = FIELDS.get((param.get("Text") or "").strip()) if param is not None else None
        if not field:
            continue
        node = rr
        function = None
        while node is not None:
            if node.tag == ns + "Channel":
                m = re.match(r"Function (\d+)", node.get("Text") or "")
                function = int(m.group(1)) if m else None
                break
            node = parent.get(node)
        if function is None:
            continue
        key = ref.get("Id")[len(prefix):]
        layout[key] = (function, field)
        defaults[key] = ref.get("Value") if ref.get("Value") is not None else (param.get("Value") or "")
    return layout, defaults


def main(params_path: str, project: str) -> int:
    layout, defaults = app_layout(project)
    icon_set = yaml.safe_load((ROOT / "icon_sets" / "schneider_dlife.yaml").read_text(encoding="utf-8"))
    by_ets = {str(i["ets"]): i["id"] for i in icon_set["icons"] if i.get("ets") is not None}
    devices = json.loads(Path(params_path).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for address, device in devices.items():
        values = device.get("parameters") or {}
        if not any(k in layout for k in values):
            continue  # not a Dynamic Labelling plate
        looks: dict[str, dict] = {}
        for key, (function, field) in layout.items():
            raw = values.get(key, {}).get("value", defaults.get(key, ""))
            control = f"b{function}"
            if field == "label":
                value = str(raw or "").strip()
            elif field == "show":
                value = SHOW.get(str(raw), "icon")
            elif field in ("icon_on", "icon_off"):
                value = by_ets.get(str(raw))
            else:
                value = COLOURS.get(str(raw))
            if value:
                # Several layout entries share one ref; a set value wins over a default.
                if key in values or field not in looks.get(control, {}):
                    looks.setdefault(control, {})[field] = value
        out[address] = dict(sorted(looks.items()))
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
