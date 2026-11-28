
from __future__ import annotations

from typing import Any, Mapping, Optional

NOT_LINEAGE_SQL: str = "(s.parent_session_id IS NULL OR s.tmux_created_epoch IS NOT NULL)"


def is_lineage_row(row: Optional[Mapping[str, Any]]) -> bool:
    if not row:
        return False
    return row.get("parent_session_id") is not None and row.get("tmux_created_epoch") is None
