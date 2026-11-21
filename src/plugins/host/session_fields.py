
from __future__ import annotations

from typing import Any, Dict, Tuple

INFO_FIELDS: Tuple[str, ...] = ("session_row_id", "label", "project_id", "activity_status", "unread", "startup_gate", "agent_family")
SESSION_FIELDS: Tuple[str, ...] = ("id", "created_at", "last_activity")
FIELDS: Tuple[str, ...] = (*SESSION_FIELDS, *INFO_FIELDS)


def _time(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def project(info: Any) -> Dict[str, Any]:
    session = getattr(info, "session", None)
    row: Dict[str, Any] = {k: _time(getattr(session, k, None)) for k in SESSION_FIELDS}
    row.update({k: getattr(info, k, None) for k in INFO_FIELDS})
    return row
