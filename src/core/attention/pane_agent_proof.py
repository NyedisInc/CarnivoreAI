
from __future__ import annotations

import subprocess
from typing import Callable, Mapping, Optional, Tuple

import structlog

from src.core.attention.registry_pane import descends_from, falls_back_to_pane, registry_for_pane
from src.core.attention.registry_read import (
    RegistryRecord,
    read_registry_index,
    registry_for_session,
)

logger = structlog.get_logger()

# could not be read
ForegroundReader = Callable[[int], Optional[Tuple[int, int]]]

# could not be read
ParentsReader = Callable[[], Optional[Mapping[int, int]]]


def read_process_group(pid: int) -> Optional[Tuple[int, int]]:
    from src.core.claude_resume_argv import PS_PATH, PS_TIMEOUT_SECONDS

    try:
        done = subprocess.run(
            [PS_PATH, "-o", "pgid=,tpgid=", "-p", str(int(pid))],
            capture_output=True, timeout=PS_TIMEOUT_SECONDS, check=False, close_fds=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("pane_agent_proof_ps_failed", pid=pid, error=str(exc))
        return None
    if done.returncode != 0:
        return None
    parts = done.stdout.decode("utf-8", "replace").split()
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def read_process_parents() -> Optional[Mapping[int, int]]:
    from src.core.claude_resume_argv import list_process_table

    rows = list_process_table()
    if rows is None:
        return None
    return {row.pid: row.ppid for row in rows}


def _registered_record(
    *, index: Mapping[str, RegistryRecord], tmux_name: Optional[str], pane_id: Optional[str],
    pane_pid: int, parents: ParentsReader, session_started_epoch: Optional[int],
    claude_session_uuid: Optional[str],
) -> RegistryRecord:
    record = registry_for_session(
        tmux_name=tmux_name, index=index,
        session_started_epoch=session_started_epoch, claude_session_uuid=claude_session_uuid,
    )
    if falls_back_to_pane(record):
        by_pane = registry_for_pane(
            index=index, pane_id=pane_id, pane_pid=pane_pid, process_parents=parents,
            session_started_epoch=session_started_epoch, claude_session_uuid=claude_session_uuid,
        )
        if by_pane is not None:
            return by_pane
    return record


def registered_agent_in_foreground(
    *,
    tmux_name: Optional[str],
    pane_id: Optional[str],
    pane_pid: Optional[int],
    session_started_epoch: Optional[int] = None,
    claude_session_uuid: Optional[str] = None,
    index: Optional[Mapping[str, RegistryRecord]] = None,
    parents: ParentsReader = read_process_parents,
    foreground: ForegroundReader = read_process_group,
) -> bool:
    if pane_pid is None or not tmux_name:
        return False
    table = index if index is not None else read_registry_index()
    snapshot: dict = {}

    def cached_parents() -> Optional[Mapping[int, int]]:
        if "parents" not in snapshot:
            snapshot["parents"] = parents()
        return snapshot["parents"]

    record = _registered_record(
        index=table, tmux_name=tmux_name, pane_id=pane_id, pane_pid=pane_pid,
        parents=cached_parents, session_started_epoch=session_started_epoch,
        claude_session_uuid=claude_session_uuid,
    )
    if not record.known or record.pid is None:
        return False
    table_parents = cached_parents()
    if table_parents is None or not descends_from(record.pid, pane_pid, table_parents):
        return False
    groups = foreground(record.pid)
    if groups is None:
        return False
    pgid, tpgid = groups
    return tpgid > 0 and pgid == tpgid
