
from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import structlog

from src.core.json_artifact import atomic_write_json, read_json_object
from src.core.notifications import catalog_lines, contracts, types

logger = structlog.get_logger(__name__)

# state directory
STATE_FILENAME = "notification_source_state.json"


@functools.lru_cache(maxsize=1)
def _labels() -> Mapping[str, str]:
    return {**catalog_lines.read_prefixed(("notify.type.",)), **catalog_lines.read_plugin_slices(("notify.type.",))}


def type_title(type_id: str) -> str:
    return _labels().get(types.get_type(type_id).label_key, type_id)


def session_fields(manager: Any, session_id: Optional[str]) -> Dict[str, Any]:
    if manager is None or not session_id:
        return {}
    session = manager._registry.sessions.get(session_id)
    tmux_name = getattr(session, "tmux_session", None)
    project, label = "", None
    if tmux_name:
        try:
            identity = manager._identity_for_live_name(tmux_name)
            project = (identity or {}).get("project_name") or ""
            label = manager._label_for_tmux_name(tmux_name)
        except (AttributeError, OSError, ValueError) as exc:
            logger.debug("notify_session_fields_unreadable", error_type=type(exc).__name__)
    return {"session_id": session_id, "tmux_name": tmux_name, "project": project,
            "session_ref": label or tmux_name or ""}


def emit_if_sink(event: contracts.NotifyEvent) -> bool:
    if not contracts.sink_installed():
        return False
    contracts.emit(event)
    return True


def now() -> float:
    return time.time()


def _state_path(state_dir: Optional[Path] = None) -> Path:
    """The state file, under ``state_dir`` or the app's state directory. Output: Path."""
    if state_dir is None:
        from src.config import settings

        state_dir = settings.get_state_dir()
    return Path(state_dir) / STATE_FILENAME


def read_state(key: str, state_dir: Optional[Path] = None) -> Optional[str]:
    doc = read_json_object(_state_path(state_dir), log_event="notify_source_state_unreadable") or {}
    value = doc.get(key)
    return value if isinstance(value, str) else None


def write_state(key: str, value: str, state_dir: Optional[Path] = None) -> bool:
    path = _state_path(state_dir)
    doc = read_json_object(path, log_event="notify_source_state_unreadable") or {}
    doc[key] = value
    return atomic_write_json(path, doc, log_event="notify_source_state_write_failed")


def fire_once(slot: str, version: str, event: contracts.NotifyEvent, state_dir: Optional[Path] = None) -> bool:
    if not contracts.sink_installed() or read_state(slot, state_dir) == version:
        return False
    contracts.emit(event)
    write_state(slot, version, state_dir)
    return True
