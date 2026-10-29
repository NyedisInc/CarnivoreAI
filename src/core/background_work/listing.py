
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

from src.core.attention.output_holders import open_file_path
from src.core.background_work.tree import PaneTree, start_instant, start_token
from src.core.timers.redact import summary as redacted_summary

SNAPSHOT_MARK: str = "/shell-snapshots/snapshot-"

MAX_LISTED: int = 20

_TASK_OUTPUT_RE = re.compile(r"/tasks/([A-Za-z0-9_-]{1,64})\.output$")
_EVAL_RE = re.compile(r"&& eval '(.*?)'(?: < /dev/null)?(?: && pwd -P >\| \S+)?\s*$", re.S)


@dataclass(frozen=True)
class ListedProcess:

    pid: int
    start: str
    task_id: Optional[str]
    started_at: Optional[datetime]
    children: int
    summary: Optional[str]


def task_id_of(stdout_path: Optional[str]) -> Optional[str]:
    match = _TASK_OUTPUT_RE.search(stdout_path or "")
    return match.group(1) if match else None


def eval_text(command: str) -> Optional[str]:
    match = _EVAL_RE.search(command or "")
    if not match:
        return None
    return match.group(1).replace("'\"'\"'", "'").replace("\\012", " ")


def _summary(tree: PaneTree, pid: int) -> Optional[str]:
    table = tree.table
    kids = [table.rows[k].command for k in sorted(table.children.get(pid, []))
            if k in table.rows]
    if kids:
        return redacted_summary(" | ".join(kids))
    return redacted_summary(eval_text(table.rows[pid].command))


def list_processes(
    tree: PaneTree,
    *,
    stdout_of: Callable[[int], Optional[str]] = lambda pid: open_file_path(pid, 1),
) -> List[ListedProcess]:
    agent = tree.agent_pid
    if agent is None:
        return []
    table = tree.table
    found: List[ListedProcess] = []
    for pid in sorted(table.children.get(agent, [])):
        row = table.rows.get(pid)
        if row is None:
            continue
        task_id = task_id_of(stdout_of(pid))
        if task_id is None and SNAPSHOT_MARK not in row.command:
            continue
        token = start_token(table, pid) or ""
        found.append(ListedProcess(
            pid=pid, start=token, task_id=task_id, started_at=start_instant(token),
            children=max(0, len(table.descendants(pid)) - 1), summary=_summary(tree, pid),
        ))
    found.sort(key=lambda item: (item.started_at is None, item.started_at or datetime.min, item.pid))
    return found[:MAX_LISTED]


__all__ = ["ListedProcess", "MAX_LISTED", "SNAPSHOT_MARK", "eval_text", "list_processes", "task_id_of"]
