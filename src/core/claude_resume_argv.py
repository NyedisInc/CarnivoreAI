
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import structlog

logger = structlog.get_logger()

PS_TIMEOUT_SECONDS: float = 3.0
PS_PATH: str = "/bin/ps" if os.path.exists("/bin/ps") else (shutil.which("ps") or "ps")

MAX_TREE_DEPTH: int = 8

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_RESUME_RE = re.compile(r"--resume(?:=|\s+)(\S+)")


@dataclass(frozen=True)
class ProcessRow:

    pid: int
    ppid: int
    command: str


PS_ARGV: List[str] = [PS_PATH, "-A", "-ww", "-o", "pid=,ppid=,lstart=,command="]

SHARED_TABLE_MAX_AGE_SECONDS: float = 2.0

_LSTART_TOKENS: int = 5

_share_lock = threading.Lock()
_share_text: Optional[str] = None
_share_taken_at: float = -1e9


def read_ps_text(max_age: float = 0.0, timeout: float = PS_TIMEOUT_SECONDS) -> Optional[str]:
    global _share_text, _share_taken_at
    with _share_lock:
        if max_age > 0 and _share_text is not None and time.monotonic() - _share_taken_at < max_age:
            return _share_text
        try:
            completed = subprocess.run(PS_ARGV, capture_output=True, timeout=timeout,
                                       check=False, close_fds=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("process_table_probe_failed", error=str(exc))
            return None
        if completed.returncode != 0:
            logger.warning("process_table_probe_nonzero_exit", returncode=completed.returncode)
            return None
        text = completed.stdout.decode("utf-8", errors="replace")
        _share_text, _share_taken_at = text, time.monotonic()
        return text


def list_process_table(timeout: float = PS_TIMEOUT_SECONDS, *, max_age: float = 0.0) -> Optional[List[ProcessRow]]:
    """Snapshot the whole process table in one `ps` call (or the shared one, see ``read_ps_text``).

    Description: macOS has no `/proc`, so this is the one place a process
      tree is ever read from - one call, walked in memory afterwards,
      rather than one `ps` per pid. NEVER RAISES: every failure mode
      answers None, which the caller must treat as "could not evaluate",
      never as "no processes".
    Inputs: timeout (float) - seconds. max_age (float) - accept a shared table this young.
    Output: list[ProcessRow] | None - every process `ps` reported, or
      None when the table could not be read at all.
    Example: list_process_table()[0].command  # '/sbin/launchd'
    """
    text = read_ps_text(max_age, timeout)
    if text is None:
        return None
    rows: List[ProcessRow] = []
    for line in text.splitlines():
        parts = line.split(None, 2 + _LSTART_TOKENS)
        if len(parts) < 3 + _LSTART_TOKENS:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        rows.append(ProcessRow(pid=pid, ppid=ppid, command=parts[2 + _LSTART_TOKENS].strip()))
    return rows


def is_claude_command(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0]
    return Path(first).name == "claude"


def _extract_resume_uuid(command: str) -> Optional[str]:
    match = _RESUME_RE.search(command)
    if not match:
        return None
    candidate = match.group(1).strip().strip("'\"")
    if not _UUID_RE.match(candidate):
        logger.warning(
            "resume_argv_uuid_malformed",
            note="a --resume value was present but not a valid uuid shape; rejected",
        )
        return None
    return candidate.lower()


def find_resume_uuid_in_tree(
    root_pid: int,
    processes: Sequence[ProcessRow],
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> Optional[str]:
    for command in find_claude_commands_in_tree(
        root_pid, processes, max_depth=max_depth
    ):
        uuid = _extract_resume_uuid(command)
        if uuid is not None:
            return uuid
    return None


def find_claude_commands_in_tree(
    root_pid: int,
    processes: Sequence[ProcessRow],
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> List[str]:
    """Every claude command line in a pane pid's process tree.

    Description: THE walk, breadth-first from `root_pid` INCLUSIVE, so
      both process topologies a pane can have are covered without a
      branch - see the module docstring. Factored out so the two readers
      of a pane's claude process share one traversal:
      :func:`find_resume_uuid_in_tree` reads a `--resume` uuid out of the
      lines this returns, and `session_agent_infer_apply` reads the flag
      set that names a wrapper out of the same lines. A second walk is
      how the two would drift about which process they are describing.

      Order is BFS-shallowest-first, which is the useful order: the pane
      pid itself comes before its descendants, so a caller taking the
      first entry gets the process closest to the pane.
    Inputs: root_pid (int) - the pane's own foreground pid.
      processes (Sequence[ProcessRow]) - a snapshot from
      :func:`list_process_table`. max_depth (int) - BFS generation cap.
    Output: list[str] - the full command line of every process in the
      walk whose argv0 basename is `claude`. EMPTY means the tree was
      walked and holds none, which is a measurement; a caller that could
      not read the table at all must not call this.
    Example: find_claude_commands_in_tree(99871, table)
      # ['claude --dangerously-skip-permissions']
    """
    return find_commands_in_tree(
        root_pid, processes, is_claude_command, max_depth=max_depth
    )


def find_rows_in_tree(
    root_pid: int,
    processes: Sequence[ProcessRow],
    matches: Callable[[str], bool],
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> List[ProcessRow]:
    by_pid: Dict[int, ProcessRow] = {row.pid: row for row in processes}
    children: Dict[int, List[int]] = {}
    for row in processes:
        children.setdefault(row.ppid, []).append(row.pid)

    found: List[ProcessRow] = []
    frontier = [root_pid]
    visited: set = set()
    depth = 0
    while frontier and depth <= max_depth:
        next_frontier: List[int] = []
        for pid in frontier:
            if pid in visited:
                continue
            visited.add(pid)
            row = by_pid.get(pid)
            if row is not None and matches(row.command):
                found.append(row)
            next_frontier.extend(children.get(pid, ()))
        frontier = next_frontier
        depth += 1
    return found


def find_commands_in_tree(
    root_pid: int,
    processes: Sequence[ProcessRow],
    matches: Callable[[str], bool],
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> List[str]:
    rows = find_rows_in_tree(root_pid, processes, matches, max_depth=max_depth)
    return [row.command for row in rows]
