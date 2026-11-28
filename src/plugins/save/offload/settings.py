
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException

from src.plugins.save.offload import constants as C
from src.plugins.sdk import vault_sources

PLUGIN_ID = "save"

DISABLED_DETAIL = "offloading is switched off: nothing is moved out of the projects folder. turn it on in the conversation backups settings."


def enabled_in(settings: Mapping[str, Any]) -> bool:
    return settings.get(C.OFFLOAD_SETTING) is True


def is_enabled(state_dir: Path) -> bool:
    return enabled_in(vault_sources.plugin_settings(state_dir, PLUGIN_ID))


def require_enabled(state_dir: Path) -> None:
    if not is_enabled(state_dir):
        raise HTTPException(status_code=409, detail={"code": C.CODE_OFFLOAD_DISABLED, "detail": DISABLED_DETAIL, "reasons": [], "stuck": []})
