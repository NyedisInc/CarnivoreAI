
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.config.workspace import ServerPrefsConfig, WorkspaceConfig
from src.core import config_writer
from src.core.workspace_settings import SERVER_PREFS_KEY, WORKSPACE_KEY


def _merge_block(
    data: Dict[str, Any], key: str, update: Optional[dict], model: type
) -> None:
    if not update:
        return
    merged = dict(data.get(key) or {})
    merged.update(update)
    model(**merged)
    data[key] = merged


def update_settings_config(
    config_path: Path,
    *,
    workspace_update: Optional[dict] = None,
    server_prefs_update: Optional[dict] = None,
) -> None:
    def merge(data: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(data)
        _merge_block(data, WORKSPACE_KEY, workspace_update, WorkspaceConfig)
        _merge_block(data, SERVER_PREFS_KEY, server_prefs_update, ServerPrefsConfig)
        return data

    config_writer.commit(config_path, merge)
