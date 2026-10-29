
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.core.subagents.tally import STATE_OK

THROTTLE_SUFFIX: str = "#subagents"


def iso_utc(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SubagentWorkStamp:

    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self._admitted: Dict[str, datetime] = {}

    def observe(
        self, session_id: str, tmux_name: Optional[str], tally: Any
    ) -> bool:
        if not tmux_name or tally is None or tally.state != STATE_OK:
            return False
        at = tally.last_activity_at
        if at is None:
            return False
        seen = self._admitted.get(session_id)
        if seen is not None and at <= seen:
            return False
        admitted = self._manager._persist_work_stamp(
            session_id, tmux_name, None,
            at=iso_utc(at), throttle_key=f"{session_id}{THROTTLE_SUFFIX}",
        )
        if admitted:
            self._admitted[session_id] = at
        return bool(admitted)


__all__ = ["SubagentWorkStamp", "THROTTLE_SUFFIX", "iso_utc"]
