
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from src.core.background_work.listing import SNAPSHOT_MARK as SHELL_SNAPSHOT_MARK
from src.core.background_work.listing import task_id_of

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


def is_tool_shell(command: str, stdout_path: Callable[[], Optional[str]]) -> bool:
    if SHELL_SNAPSHOT_MARK in (command or ""):
        return True
    return task_id_of(stdout_path()) is not None


def measure_background(
    claude_pid: Optional[int],
    snapshot: Optional[ProcessSnapshot],
    *,
    stdout_of: Callable[[int], Optional[str]],
) -> BackgroundMeasure:
    if claude_pid is None:
        return BackgroundMeasure(STATE_UNKNOWN, None, "no claude pid is known")
    if snapshot is None or not snapshot.ok or not snapshot.parents:
        return BackgroundMeasure(STATE_UNKNOWN, None, "the process table could not be read")
    if claude_pid not in snapshot.parents:
        return BackgroundMeasure(
            STATE_UNKNOWN, None, "claude pid %d is not in the process table" % claude_pid,
        )
    count = 0
    for pid, ppid in snapshot.parents.items():
        if ppid != claude_pid or pid == claude_pid:
            continue
        if is_tool_shell(snapshot.commands.get(pid, ""), lambda pid=pid: stdout_of(pid)):
            count += 1
    if count:
        return BackgroundMeasure(
            STATE_RUNNING, count, "%d tool shell(s) running under claude pid %d" % (count, claude_pid),
        )
    return BackgroundMeasure(STATE_NONE, 0, "no tool shell runs under claude pid %d" % claude_pid)


__all__ = [
    "ALL_STATES", "BackgroundMeasure", "ProcessSnapshot", "SHELL_SNAPSHOT_MARK",
    "STATE_NONE", "STATE_RUNNING", "STATE_UNKNOWN", "UNREADABLE", "is_tool_shell",
    "measure_background",
]
