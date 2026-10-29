
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

from src.core import libproc_snapshot

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
    snap = libproc_snapshot.snapshot(max_age)
    if snap is not None:
        return [ProcessRow(pid=r.pid, ppid=r.ppid, command=r.command) for r in snap]
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
