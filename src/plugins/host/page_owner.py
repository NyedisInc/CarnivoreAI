
from __future__ import annotations

import re
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, urlsplit

from src.plugins.host.runtime import definitions, listed
from src.plugins.sdk import CplugDefinition

APP_KEY_PREFIX = "app:"


def _word(raw: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-") or "x"


def _popout_flag(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        enabled = value.get("enabled")
        return enabled if isinstance(enabled, bool) else True
    return None


def _sidecar_owns_tab(d: CplugDefinition, tab: str) -> bool:
    m = d.manifest
    ui_meta = getattr(m, "ui_meta", None)
    ui_popout = _popout_flag(ui_meta.get("popout")) if isinstance(ui_meta, Mapping) else None
    base_tab = f"cplug-{_word(d.id)}"
    page = getattr(m, "page", None)
    has_page = isinstance(page, Mapping)
    if has_page:
        page_popout = _popout_flag(page.get("popout"))
        if (page_popout if page_popout is not None else ui_popout) is True and tab == base_tab:
            return True
    st = ui_meta.get("sidebar_tab") if isinstance(ui_meta, Mapping) else None
    if isinstance(st, Mapping):
        st_popout = _popout_flag(st.get("popout"))
        if (st_popout if st_popout is not None else ui_popout) is True:
            st_id = st.get("id")
            explicit_id = _word(st_id.strip()) if isinstance(st_id, str) and st_id.strip() else ""
            expected = f"{base_tab}-{explicit_id or 'tab'}" if (has_page or explicit_id) else base_tab
            if tab == expected or (not has_page and tab == base_tab):
                return True
    return False


def tab_of(key: str) -> Optional[str]:
    if not key.startswith(APP_KEY_PREFIX):
        return None
    tab = parse_qs(urlsplit(key[len(APP_KEY_PREFIX):]).query).get("tab")
    return tab[0] if tab and tab[0] else None


def owner_of(key: str) -> Optional[CplugDefinition]:
    tab = tab_of(key)
    if tab is None:
        return None
    compiled = next((d for d in definitions() if tab in d.manifest.surfaces.tabs), None)
    if compiled is not None:
        return compiled
    return next((d for d in listed() if _sidecar_owns_tab(d, tab)), None)
