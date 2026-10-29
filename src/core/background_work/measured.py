"""Is anything of this session's actually running in the background? MEASURED
from the process tree, not read from a flag (issue #1185).

THE RULE: WHAT COUNTS AS WORK UNDER CLAUDE. A direct child of the claude
process is the session's work when it carries Claude Code's own TOOL
SHELL signature, either one of:

EVERYTHING ELSE CLAUDE STARTS DIRECTLY IS CLAUDE'S OWN MACHINERY: its MCP
servers (``npm exec @modelcontextprotocol/...`` on stdio pipes), the
``caffeinate -i -t 300`` it holds while working, its status line and hook
commands, the chrome native host. Measured the same day under a live
claude: two MCP servers and one caffeinate beside five tool shells. This
is deliberately a POSITIVE signature of work rather than a list of helper
names to subtract: a new MCP server, a new helper binary or a plugin's LSP
server can never read as background work, and no name list needs keeping.

WHY DIRECT CHILDREN ONLY. A tool shell's own children live under it and
count with it (one shell is one piece of work, however many processes it
runs). A process that outlived its shell re-parented to launchd and is not
this session's any more (the same rule as ``attention.output_holders``).

THREE ANSWERS, NEVER TWO. ``running`` (with a count), ``none``, and
``unknown`` when the table could not be read, no claude pid is known, or
that pid is not in the table. Unknown is never idle.

COST. No subprocess of its own: it walks the ONE ``ps`` snapshot the
attention reader already takes per watcher pass
(``AttentionEvidenceReader._process_snapshot``), plus one ``proc_pidfdinfo``
per direct child without the snapshot mark (an MCP server, a caffeinate).
"""

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
    """One ``ps`` snapshot, walked in memory by every pane of one pass.

    Attributes: parents (Mapping[int, int]) - pid to parent pid. commands
      (Mapping[int, str]) - pid to its command line. ok (bool) - False when
      the table could not be read (then both maps are empty).
    """

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
