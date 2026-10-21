from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.button_blueprinter.const import VERSION

ROOT = Path(__file__).parents[2] / "custom_components" / "button_blueprinter"


def test_versions_agree():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    page = (ROOT / "www" / "button-blueprinter.js").read_text(encoding="utf-8")
    assert manifest["version"] == VERSION
    assert re.search(r'const PAGE_VERSION = "([^"]+)"', page).group(1) == VERSION


def test_strings_match_translations():
    assert (ROOT / "strings.json").read_text(encoding="utf-8") == (ROOT / "translations" / "en.json").read_text(encoding="utf-8")
