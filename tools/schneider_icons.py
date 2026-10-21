"""Copy Schneider's D-Life icon pictures out of an ETS project file.

The pictures are Schneider's (ETS product data), so they are not in this
repository. They sit unencrypted in any .knxproj that contains a Schneider
D-Life push button, at M-0064/Baggages/Icon_Product_preview.zip.

Usage:

    python tools/schneider_icons.py MyHouse.knxproj OUT_FOLDER

Writes OUT_FOLDER/schneider_dlife/<file> for every icon named in
custom_components/button_blueprinter/icon_sets/schneider_dlife.yaml. Copy
OUT_FOLDER's contents into Home Assistant's config folder as
`button_blueprinter_icons/` and restart; the page then shows the real icons.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import yaml

SET = Path(__file__).parents[1] / "custom_components" / "button_blueprinter" / "icon_sets" / "schneider_dlife.yaml"
BAGGAGE = "M-0064/Baggages/Icon_Product_preview.zip"


def main(project: str, out: str) -> int:
    icon_set = yaml.safe_load(SET.read_text(encoding="utf-8"))
    wanted = {i["file"] for i in icon_set["icons"] if i.get("file")}
    with zipfile.ZipFile(project) as outer:
        try:
            inner_bytes = outer.read(BAGGAGE)
        except KeyError:
            print(f"{project} has no {BAGGAGE}: is there a Schneider D-Life push button in it?")
            return 1
    folder = Path(out) / icon_set["id"]
    folder.mkdir(parents=True, exist_ok=True)
    found = 0
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        for name in inner.namelist():
            if name in wanted:
                (folder / name).write_bytes(inner.read(name))
                found += 1
    missing = sorted(wanted - {p.name for p in folder.iterdir()})
    print(f"{found} icons written to {folder}")
    if missing:
        print("Not in this project's product data:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
