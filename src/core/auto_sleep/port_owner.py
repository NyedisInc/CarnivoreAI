
from __future__ import annotations

import subprocess
from typing import Callable, Dict, FrozenSet, Optional

from src.core.auto_sleep.pane_listeners import (
    LSOF_PATH,
    LSOF_TIMEOUT_SECONDS,
    MeasureError,
    parse_lsof_pids,
)
from src.core.conversation_writers import ProcessTable, read_process_table
from src.core.tmux_discovery import tmux_argv_prefix

__all__ = ["find_port_owner", "owner_of_listeners", "pane_pid_sessions", "port_listener_pids"]

TMUX_TIMEOUT_SECONDS: float = 5.0


def port_listener_pids(port: int) -> FrozenSet[int]:
    try:
        proc = subprocess.run(
            [LSOF_PATH, "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True, text=True, timeout=LSOF_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MeasureError(f"lsof could not run: {type(exc).__name__}") from exc
    if proc.returncode == 1 and not proc.stdout.strip():
        return frozenset()
    if proc.returncode != 0:
        raise MeasureError(f"lsof exited {proc.returncode}")
    return parse_lsof_pids(proc.stdout)


def pane_pid_sessions(
    socket: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Dict[int, str]:
    argv = tmux_argv_prefix(socket) + ["list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}"]
    try:
        done = runner(argv, capture_output=True, text=True,
                      timeout=TMUX_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MeasureError(f"tmux could not run: {type(exc).__name__}") from exc
    if done.returncode != 0:
        if "no server running" in (done.stderr or ""):
            return {}
        raise MeasureError(f"tmux list-panes exited {done.returncode}")
    out: Dict[int, str] = {}
    for line in (done.stdout or "").splitlines():
        name, _, raw_pid = line.partition("\t")
        try:
            out[int(raw_pid)] = name
        except ValueError:
            continue
    return out


def owner_of_listeners(
    listeners: FrozenSet[int], panes: Dict[int, str], table: ProcessTable
) -> Optional[str]:
    for pid in sorted(listeners):
        seen = set()
        while pid in table.rows and pid not in seen:
            if pid in panes:
                return panes[pid]
            seen.add(pid)
            pid = table.rows[pid].ppid
    return None


def find_port_owner(port: int, socket: str) -> Optional[str]:
    listeners = port_listener_pids(port)
    if not listeners:
        return None
    panes = pane_pid_sessions(socket)
    if not panes:
        return None
    return owner_of_listeners(listeners, panes, read_process_table())
