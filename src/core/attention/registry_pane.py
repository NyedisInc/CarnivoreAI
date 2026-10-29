
from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Mapping, Optional

from src.core.attention.parent_map import descends_from
from src.core.attention.registry_record import (
    REG_ABSENT,
    REG_OK,
    REG_STALE,
    REG_UNREADABLE,
    RegistryRecord,
    _empty_record,
)
from src.core.attention.registry_index import registry_for_session

ProcessParents = Callable[[], Optional[Mapping[int, int]]]


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
            ambiguous_pane=True,
        )
    key, _record = proven[0]
    return registry_for_session(
        tmux_name=key,
        index=index,
        session_started_epoch=session_started_epoch,
        claude_session_uuid=claude_session_uuid,
        process_floor_at=process_floor_at,
    )
