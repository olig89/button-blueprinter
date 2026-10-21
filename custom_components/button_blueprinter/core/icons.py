"""Icon sets: the fixed icons a kind of switch can show (one YAML file per set).

A switch model either takes any Material Design icon (``mdi:…``) on its buttons,
or names an icon set, and then its buttons may only show icons from that set,
because that's all the real switch can show. No Home Assistant imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MDI = re.compile(r"^mdi:[a-z0-9-]+$")


class IconSetError(ValueError):
    pass


@dataclass(frozen=True)
class Icon:
    id: str
    name: str
    mdi: str  # the look-alike shown when the real picture isn't installed
    ets: int | None = None  # the ETS parameter value, where the switch has one
    file: str | None = None  # the real picture's file name, where there is one

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in {"id": self.id, "name": self.name, "mdi": self.mdi, "ets": self.ets, "file": self.file}.items() if v is not None}


@dataclass(frozen=True)
class IconSet:
    id: str
    name: str
    icons: dict[str, Icon] = field(default_factory=dict)

    def by_ets(self, value: int) -> Icon | None:
        return next((i for i in self.icons.values() if i.ets == value), None)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "icons": [i.as_dict() for i in self.icons.values()]}


def parse_icon_set(data: Any, source: str = "icon set") -> IconSet:
    if not isinstance(data, dict) or not data.get("id") or not isinstance(data.get("icons"), list):
        raise IconSetError(f"{source}: needs an id and a list of icons")
    icons: dict[str, Icon] = {}
    for i, raw in enumerate(data["icons"]):
        where = f"{source} icon {i + 1}"
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("name"):
            raise IconSetError(f"{where}: needs an id and a name")
        if raw["id"] in icons:
            raise IconSetError(f"{where}: id '{raw['id']}' used twice")
        if not MDI.match(str(raw.get("mdi", ""))):
            raise IconSetError(f"{where}: 'mdi' must be an icon name like mdi:lightbulb")
        ets = raw.get("ets")
        if ets is not None and not isinstance(ets, int):
            raise IconSetError(f"{where}: 'ets' must be a whole number")
        icons[raw["id"]] = Icon(id=raw["id"], name=str(raw["name"]), mdi=raw["mdi"], ets=ets, file=raw.get("file"))
    return IconSet(id=str(data["id"]), name=str(data.get("name", data["id"])), icons=icons)
