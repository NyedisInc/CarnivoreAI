
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from src.core.background_work.listing import SNAPSHOT_MARK as SHELL_SNAPSHOT_MARK
from src.core.background_work.listing import is_agy_tool_shell, task_id_of

STATE_RUNNING: str = "running"
STATE_NONE: str = "none"
STATE_UNKNOWN: str = "unknown"

ALL_STATES = frozenset({STATE_RUNNING, STATE_NONE, STATE_UNKNOWN})


@dataclass(frozen=True)
class ProcessSnapshot:

    parents: Mapping[int, int]
    commands: Mapping[int, str]
    ok: bool = True


UNREADABLE = ProcessSnapshot(parents={}, commands={}, ok=False)


@dataclass(frozen=True)
class BackgroundMeasure:

    state: str
    count: Optional[int]
    detail: str = ""
    servers: int = 0


def is_tool_shell(command: str, stdout_path: Callable[[], Optional[str]]) -> bool:
    if SHELL_SNAPSHOT_MARK in (command or ""):
        return True
    return task_id_of(stdout_path()) is not None


def tree_pids(snapshot: ProcessSnapshot, root: int) -> List[int]:
    children: Dict[int, List[int]] = {}
    for pid, ppid in snapshot.parents.items():
        children.setdefault(ppid, []).append(pid)
    found, queue, seen = [], [root], {root}
    while queue:
        pid = queue.pop(0)
        found.append(pid)
        for child in children.get(pid, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return found


def measure_background(
    claude_pid: Optional[int],
    snapshot: Optional[ProcessSnapshot],
    *,
    stdout_of: Callable[[int], Optional[str]],
    is_server: Optional[Callable[[int, str, List[int]], bool]] = None,
    agent_kind: str = "claude",
) -> BackgroundMeasure:
    if claude_pid is None:
        return BackgroundMeasure(STATE_UNKNOWN, None, "no %s pid is known" % agent_kind)
    if snapshot is None or not snapshot.ok or not snapshot.parents:
        return BackgroundMeasure(STATE_UNKNOWN, None, "the process table could not be read")
    if claude_pid not in snapshot.parents:
        return BackgroundMeasure(
            STATE_UNKNOWN, None, "%s pid %d is not in the process table" % (agent_kind, claude_pid),
        )
    count = 0
    servers = 0
    for pid, ppid in snapshot.parents.items():
        if ppid != claude_pid or pid == claude_pid:
            continue
        command = snapshot.commands.get(pid, "")
        matched = (
            is_agy_tool_shell(command)
            if agent_kind == "agy"
            else is_tool_shell(command, lambda pid=pid: stdout_of(pid))
        )
        if matched:
            count += 1
            if is_server is not None and is_server(pid, command, tree_pids(snapshot, pid)):
                servers += 1
    if count:
        return BackgroundMeasure(
            STATE_RUNNING, count, "%d tool shell(s) running under %s pid %d" % (count, agent_kind, claude_pid),
            servers=servers,
        )
    return BackgroundMeasure(STATE_NONE, 0, "no tool shell runs under %s pid %d" % (agent_kind, claude_pid))


__all__ = [
    "ALL_STATES", "BackgroundMeasure", "ProcessSnapshot", "SHELL_SNAPSHOT_MARK",
    "STATE_NONE", "STATE_RUNNING", "STATE_UNKNOWN", "UNREADABLE", "is_tool_shell",
    "measure_background", "tree_pids",
]
