
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Sequence, Tuple

import structlog

from src.core.backup_health import offloaded_marker
from src.core.deepsearch import fallback_hook

logger = structlog.get_logger()

RESUME_FLAGS: Tuple[str, ...] = ("--resume", "-r")
OFFLOADED_CODE: str = "offloaded"
RESTORE_ROUTE: str = "/offload/sessions/{session_uuid}/restore"
SAVE_SOURCE_ID: str = "save"
DETAIL_RESTORE: str = "this conversation was offloaded to the backup vault; restore it first, then open the session"
DETAIL_TURN_ON: str = "this conversation was offloaded to the backup vault; turn backups on to restore it"
DETAIL_UNREADABLE: str = "the list of offloaded conversations could not be read, so this missing conversation is not started fresh; check conversation backups"


@dataclass(frozen=True)
class OffloadedInfo:

    conversation_id: str
    sessions: Tuple[str, ...]
    bytes: int
    plugin_on: bool
    unreadable: bool = False
    offloaded_at: float = 0.0

    @property
    def detail(self) -> str:
        if self.unreadable:
            return DETAIL_UNREADABLE
        return DETAIL_RESTORE if self.plugin_on else DETAIL_TURN_ON


def plugin_on() -> bool:
    return fallback_hook.registered(SAVE_SOURCE_ID) or fallback_hook.booting()


def _state_dir() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.get_state_dir())


def lookup(conversation_id: Optional[str]) -> Optional[OffloadedInfo]:
    if not conversation_id:
        return None
    marker = offloaded_marker.read(_state_dir())
    if marker.unreadable:
        return OffloadedInfo(conversation_id, (), 0, plugin_on(), unreadable=True)
    row = marker.rows.get(conversation_id)
    if row is None:
        return None
    return OffloadedInfo(conversation_id, row.sessions, row.bytes, plugin_on(), offloaded_at=row.offloaded_at)


def resumed_offloaded(agent_extra_args: Optional[Sequence[str]]) -> Optional[OffloadedInfo]:
    args = list(agent_extra_args or ())
    named = [args[i + 1] for i, flag in enumerate(args[:-1]) if flag in RESUME_FLAGS]
    if not named:
        return None
    marker = offloaded_marker.read(_state_dir())
    for conversation_id in named:
        row = marker.rows.get(conversation_id)
        if row is not None:
            return OffloadedInfo(conversation_id, row.sessions, row.bytes, plugin_on(), offloaded_at=row.offloaded_at)
    return None


def refusal_body(info: OffloadedInfo) -> Dict[str, Any]:
    return {"code": OFFLOADED_CODE, "detail": info.detail, "conversations": [info.conversation_id], "sessions": list(info.sessions),
            "bytes": info.bytes, "restore_route": RESTORE_ROUTE, "plugin_on": info.plugin_on, "offloaded_at": info.offloaded_at}


def summary(session_uuid: Optional[str] = None, conversation_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    marker = offloaded_marker.read(_state_dir())
    if marker.unreadable:
        return {**refusal_body(OffloadedInfo(conversation_id or "", (), 0, plugin_on(), unreadable=True)), "unreadable": True}
    hits = {cid: row for cid, row in marker.rows.items()
            if (conversation_id is not None and cid == conversation_id) or (session_uuid is not None and session_uuid in row.sessions)}
    if not hits:
        return None
    sessions = sorted({s for row in hits.values() for s in row.sessions})
    on = plugin_on()
    detail = DETAIL_RESTORE if on else DETAIL_TURN_ON
    return {"code": OFFLOADED_CODE, "detail": detail, "conversations": sorted(hits), "sessions": sessions, "bytes": sum(r.bytes for r in hits.values()),
            "offloaded_at": max(r.offloaded_at for r in hits.values()), "restore_route": RESTORE_ROUTE, "plugin_on": on, "unreadable": False}


def offloaded_ids() -> FrozenSet[str]:
    return frozenset(offloaded_marker.read(_state_dir()).rows)
