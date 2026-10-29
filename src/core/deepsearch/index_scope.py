
from __future__ import annotations

from typing import Any, Callable, FrozenSet, Mapping, Optional

import structlog

from src.core.deepsearch import constants as K
from src.core.transcript_source import scope as scope_mod

logger = structlog.get_logger()

PLUGIN_ID: str = "deepsearch"
PREFERENCE_FIELD: str = "deepsearch_index_scope"
SCOPES = (scope_mod.SCOPE_HUMAN, scope_mod.SCOPE_SUBSESSIONS, scope_mod.SCOPE_ALL)
_last_read: str = K.INDEX_SCOPE
_read_preferences: Optional[Callable[[], Mapping[str, Any]]] = None


def install(read_preferences: Callable[[], Mapping[str, Any]]) -> None:
    global _read_preferences
    _read_preferences = read_preferences


def uninstall() -> None:
    global _read_preferences
    _read_preferences = None


def read() -> Optional[str]:
    global _last_read
    if _read_preferences is None:
        return K.INDEX_SCOPE
    try:
        values = _read_preferences().get("values")
    except (OSError, ValueError) as exc:
        logger.error("deepsearch_index_scope_unreadable", error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    stored = values.get(PREFERENCE_FIELD) if isinstance(values, Mapping) else None
    _last_read = stored if stored in SCOPES else K.INDEX_SCOPE
    return _last_read


def current() -> str:
    value = read()
    return value if value is not None else _last_read


def file_kinds() -> FrozenSet[str]:
    kinds = {K.FILE_CONVERSATION}
    if scope_mod.includes_subagents(current()):
        kinds.add(K.FILE_SUBAGENT)
    return frozenset(kinds)
