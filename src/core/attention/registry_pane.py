
from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Mapping, Optional, Set

from src.core.attention.registry_read import (
    REG_ABSENT,
    REG_OK,
    REG_STALE,
    REG_UNREADABLE,
    RegistryRecord,
    _empty_record,
    registry_for_session,
)

# could not be read
ProcessParents = Callable[[], Optional[Mapping[int, int]]]


def descends_from(pid: int, root_pid: int, parents: Mapping[int, int]) -> bool:
    visited: Set[int] = set()
    while pid > 0 and pid not in visited:
        if pid == root_pid:
            return True
        visited.add(pid)
        pid = parents.get(pid, 0)
    return False


def falls_back_to_pane(registry: RegistryRecord) -> bool:
    if registry.verdict == REG_ABSENT:
        return True
    return registry.verdict == REG_STALE and not registry.instance_present


def registry_for_pane(
    *,
    index: Mapping[str, RegistryRecord],
    pane_id: Optional[str],
    pane_pid: Optional[int],
    process_parents: Optional[ProcessParents],
    session_started_epoch: Optional[int],
    claude_session_uuid: Optional[str],
    process_floor_at: Optional[datetime] = None,
) -> Optional[RegistryRecord]:
    if not pane_id or pane_pid is None or process_parents is None:
        return None
    candidates: List[tuple] = [
        (key, record) for key, record in index.items()
        if record.verdict == REG_OK and record.pane_id == pane_id
        and record.pid is not None
    ]
    if not candidates:
        return None
    parents = process_parents()
    if parents is None:
        return None
    proven = [
        (key, record) for key, record in candidates
        if descends_from(record.pid, pane_pid, parents)
    ]
    if not proven:
        return None
    if len(proven) > 1:
        return _empty_record(
            REG_UNREADABLE,
            "two or more live registry records name tmux pane %s: pids %s"
            % (pane_id, ", ".join(str(record.pid) for _key, record in proven)),
        )
    key, _record = proven[0]
    return registry_for_session(
        tmux_name=key,
        index=index,
        session_started_epoch=session_started_epoch,
        claude_session_uuid=claude_session_uuid,
        process_floor_at=process_floor_at,
    )
