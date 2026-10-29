
from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlsplit

from src.cplugs.host.runtime import definitions
from src.cplugs.sdk import CplugDefinition

APP_KEY_PREFIX = "app:"


def tab_of(key: str) -> Optional[str]:
    if not key.startswith(APP_KEY_PREFIX):
        return None
    tab = parse_qs(urlsplit(key[len(APP_KEY_PREFIX):]).query).get("tab")
    return tab[0] if tab and tab[0] else None


def owner_of(key: str) -> Optional[CplugDefinition]:
    tab = tab_of(key)
    if tab is None:
        return None
    return next((d for d in definitions() if tab in d.manifest.surfaces.tabs), None)
