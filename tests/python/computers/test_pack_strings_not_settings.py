
from __future__ import annotations

import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
ENTRY = re.compile(r"^\s*'([a-z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)'", re.M)
ROUTES_VIA_SETTINGS = re.compile(
    r"(from|in|under|open|to)\s+(its own |the |your |this computer's |its )?(pack )?settings\b"
    r"|\bsettings,? (signed in|pack|hosts|computers)|open pack settings", re.I)
PACK_WORD = re.compile(r"\b(pack|computers?|join(ing)?|hosts?)\b", re.I)
ALLOWED_PREFIXES = ("settings.", "cplug.", "automations.")
ALLOWED_PHRASE = re.compile(r"system settings|notification settings|claude settings", re.I)


def test_no_catalog_value_routes_pack_through_settings() -> None:
    entries = ENTRY.findall(CATALOG.read_text())
    assert len(entries) > 1000, "extractor found nothing: the check would pass blind"
    bad = []
    for key, value in entries:
        if key.startswith(ALLOWED_PREFIXES) or key == "pack.machines.settings_title":
            continue
        cleaned = ALLOWED_PHRASE.sub("", value)
        if ROUTES_VIA_SETTINGS.search(cleaned) and PACK_WORD.search(cleaned):
            bad.append(key)
    assert not bad, f"these values still send the user to Settings for Pack: {bad}"
