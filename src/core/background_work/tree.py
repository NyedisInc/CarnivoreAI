
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import structlog

from src.core.claude_resume_argv import is_claude_command
from src.core.codex_process_infer import is_codex_command
from src.core.conversation_writers import (
    MeasureError,
    ProcessTable,
    normalise_lstart,
    read_process_table,
)
from src.core.tmux_transport.run import tmux_run_text

logger = structlog.get_logger(__name__)

PANE_PROBE_TIMEOUT_SECONDS: float = 5.0

MAX_ANCESTRY_HOPS: int = 64

_LSTART_FORMAT: str = "%a %b %d %H:%M:%S %Y"


class TreeError(Exception):
    pass


class PaneNotFound(TreeError):
    pass


class TreeUnmeasured(TreeError):
    pass


@dataclass(frozen=True)
class PaneTree:

    tmux_name: str
    socket: str
    pane_pids: Tuple[int, ...]
    table: ProcessTable
    agent_pid: Optional[int]


def is_agent_command(command: str) -> bool:
    return is_claude_command(command) or is_codex_command(command)


def probe_pane_pids(
    name: str,
    socket: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Tuple[int, ...]:
    if not name or ":" in name or "." in name:
        raise PaneNotFound(f"unusable tmux session name {name!r}")
    done = tmux_run_text(socket, "list-panes", "-s", "-t", f"={name}:", "-F",
                         "#{session_name}\t#{pane_pid}", timeout=PANE_PROBE_TIMEOUT_SECONDS,
                         runner=runner)
    if done.error:
        raise TreeUnmeasured(f"tmux could not run: {done.error}")
    if done.returncode != 0:
        stderr = done.stderr.strip()
        if "can't find" in stderr or "no server running" in stderr:
            raise PaneNotFound(f"no session {name!r} on socket {socket!r}")
        raise TreeUnmeasured(f"tmux list-panes exited {done.returncode}: {stderr[:200]}")
    pids: List[int] = []
    for line in done.stdout.splitlines():
        session_name, _, raw_pid = line.partition("\t")
        if session_name != name:
            continue
        try:
            pids.append(int(raw_pid))
        except ValueError:
            continue
    if not pids:
        raise PaneNotFound(f"session {name!r} listed no pane of its own")
    return tuple(pids)


def find_agent(table: ProcessTable, pane_pids: Tuple[int, ...]) -> Optional[int]:
    for pane_pid in pane_pids:
        for proc in table.descendants(pane_pid):
            if is_agent_command(proc.command):
                return proc.pid
    return None


def ancestry(table: ProcessTable, pid: int) -> List[int]:
    chain: List[int] = []
    current = pid
    while current > 1 and current in table.rows and current not in chain:
        chain.append(current)
        if len(chain) > MAX_ANCESTRY_HOPS:
            break
        current = table.rows[current].ppid
    return chain


def is_strictly_below(table: ProcessTable, pid: int, ancestor: int) -> bool:
    return pid != ancestor and ancestor in ancestry(table, pid)[1:]


def start_token(table: ProcessTable, pid: int) -> Optional[str]:
    row = table.rows.get(pid)
    return normalise_lstart(row.lstart) if row is not None else None


def start_instant(token: Optional[str]) -> Optional[datetime]:
    if not token:
        return None
    try:
        epoch = time.mktime(time.strptime(normalise_lstart(token), _LSTART_FORMAT))
    except (ValueError, OverflowError):
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def measure(
    name: str,
    socket: str,
    *,
    table_reader: Callable[[], ProcessTable] = read_process_table,
    pane_probe: Callable[[str, str], Tuple[int, ...]] = probe_pane_pids,
) -> PaneTree:
    pane_pids = pane_probe(name, socket)
    try:
        table = table_reader()
    except MeasureError as exc:
        raise TreeUnmeasured(str(exc)) from exc
    return PaneTree(
        tmux_name=name, socket=socket, pane_pids=pane_pids, table=table,
        agent_pid=find_agent(table, pane_pids),
    )


__all__ = [
    "MAX_ANCESTRY_HOPS", "PaneNotFound", "PaneTree", "TreeError", "TreeUnmeasured",
    "ancestry", "find_agent", "is_agent_command", "is_strictly_below", "measure",
    "probe_pane_pids", "start_instant", "start_token",
]
