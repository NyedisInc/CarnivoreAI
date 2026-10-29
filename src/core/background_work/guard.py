
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional, Tuple

from src.core.background_work.tree import (
    PaneTree,
    ancestry,
    is_agent_command,
    is_strictly_below,
    start_token,
)
from src.core.conversation_writers import normalise_lstart

REFUSE_INVALID_PID: str = "invalid_pid"
REFUSE_NO_AGENT: str = "no_agent_process"
REFUSE_GONE: str = "process_gone"
REFUSE_START_MISMATCH: str = "start_mismatch"
REFUSE_NOT_DESCENDANT: str = "not_descendant"
REFUSE_PANE_PROCESS: str = "pane_process"
REFUSE_AGENT_PROCESS: str = "agent_process"
REFUSE_SELF: str = "server_process"

REFUSALS: Tuple[str, ...] = (
    REFUSE_INVALID_PID, REFUSE_NO_AGENT, REFUSE_GONE, REFUSE_START_MISMATCH,
    REFUSE_NOT_DESCENDANT, REFUSE_PANE_PROCESS, REFUSE_AGENT_PROCESS, REFUSE_SELF,
)


@dataclass(frozen=True)
class Verdict:

    allowed: bool
    code: Optional[str]
    detail: str
    subtree: Tuple[Tuple[int, str], ...] = ()


def _refuse(code: str, detail: str) -> Verdict:
    return Verdict(allowed=False, code=code, detail=detail)


def server_lineage() -> FrozenSet[int]:
    return frozenset({os.getpid(), os.getppid()})


def check(
    tree: PaneTree,
    pid: int,
    start: str,
    *,
    self_pids: Iterable[int] = (),
) -> Verdict:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return _refuse(REFUSE_INVALID_PID, f"{pid!r} is not a process this route can signal")
    table = tree.table
    protected = set()
    for own in self_pids:
        protected.update(ancestry(table, own) or [own])
    if pid in protected:
        return _refuse(REFUSE_SELF, f"pid {pid} is this server or one of its parents")
    if pid in tree.pane_pids:
        return _refuse(REFUSE_PANE_PROCESS, f"pid {pid} is the pane's own process")
    if tree.agent_pid is None:
        return _refuse(REFUSE_NO_AGENT, "no claude or codex process runs in this pane")
    if pid == tree.agent_pid:
        return _refuse(REFUSE_AGENT_PROCESS, f"pid {pid} is the session's agent process")
    measured = start_token(table, pid)
    if measured is None:
        return _refuse(REFUSE_GONE, f"pid {pid} is not running")
    if measured != normalise_lstart(start or ""):
        return _refuse(
            REFUSE_START_MISMATCH,
            f"pid {pid} started at {measured!r}, not {start!r}: a different process",
        )
    if not is_strictly_below(table, pid, tree.agent_pid):
        above = pid in ancestry(table, tree.agent_pid)
        code = REFUSE_PANE_PROCESS if above else REFUSE_NOT_DESCENDANT
        where = "above the agent in the pane" if above else "not under this session's agent"
        return _refuse(code, f"pid {pid} is {where}")
    if is_agent_command(table.rows[pid].command):
        return _refuse(REFUSE_AGENT_PROCESS, f"pid {pid} is itself an agent process")
    subtree = tuple(
        (proc.pid, normalise_lstart(proc.lstart))
        for proc in table.descendants(pid)
        if proc.pid not in protected
    )
    return Verdict(
        allowed=True, code=None,
        detail=f"pid {pid} is under the agent (pid {tree.agent_pid})",
        subtree=subtree,
    )


__all__ = [
    "REFUSALS", "REFUSE_AGENT_PROCESS", "REFUSE_GONE", "REFUSE_INVALID_PID",
    "REFUSE_NOT_DESCENDANT", "REFUSE_NO_AGENT", "REFUSE_PANE_PROCESS", "REFUSE_SELF",
    "REFUSE_START_MISMATCH", "Verdict", "check", "server_lineage",
]
