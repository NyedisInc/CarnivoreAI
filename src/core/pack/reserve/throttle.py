
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.pack.load import process_tree
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

PRIO_DARWIN_PROCESS = 4
PRIO_DARWIN_BG = 0x1000
TICK_SECONDS = 10.0
CLEAR_AFTER_SECONDS = 60.0
CLEAR_MARGIN = 0.05

SetPriority = Callable[[int, int, int], None]
_AGENT_SESSIONS_SQL = ("SELECT s.tmux_socket, s.tmux_name FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
                       "JOIN swarm_wakes w ON w.agent_id = a.id AND w.ended_at IS NULL "
                       "WHERE a.torn_down_at IS NULL AND s.tmux_name IS NOT NULL "
                       "UNION SELECT s.tmux_socket, s.tmux_name FROM swarm_remote_bodies b JOIN sessions s ON s.id = b.session_row_id "
                       "WHERE b.torn_down_at IS NULL AND s.tmux_name IS NOT NULL")


def set_background(pid: int, on: bool, *, setpriority: Optional[SetPriority] = None) -> bool:
    call = setpriority or os.setpriority
    try:
        call(PRIO_DARWIN_PROCESS, pid, PRIO_DARWIN_BG if on else 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError as exc:
        logger.info("pack_throttle_setpriority_failed", pid=pid, error=type(exc).__name__)
        return False


def agent_pane_pids(open_db: Callable[[], sqlite3.Connection], *, run: Optional[Callable[[List[str]], Optional[str]]] = None) -> List[int]:
    with closing(open_db()) as conn:
        wanted: Dict[str, Set[str]] = {}
        for socket, name in conn.execute(_AGENT_SESSIONS_SQL):
            wanted.setdefault(str(socket), set()).add(str(name))
    reader = run or _run
    pids: List[int] = []
    for socket, names in wanted.items():
        try:
            argv = tmux_argv_prefix(socket)
        except TmuxVersionSkewError:
            continue
        out = reader(argv + ["list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}\t#{session_attached}"])
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] in names and parts[1].isdigit() and parts[2] == "0":
                pids.append(int(parts[1]))
    return pids


def _run(argv: List[str]) -> Optional[str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


class Throttle:

    def __init__(self, *, measure: Callable[[], Optional[Tuple[float, float, int]]], roots: Callable[[], List[int]],
                 ps: Callable[[], Optional[List[process_tree.Proc]]] = process_tree.read, setpriority: Optional[SetPriority] = None,
                 clock: Callable[[], float] = time.monotonic, enabled: Optional[bool] = None) -> None:
        self._measure, self._roots, self._ps, self._set, self._clock = measure, roots, ps, setpriority, clock
        self.enabled = sys.platform == "darwin" if enabled is None else enabled
        self.throttled: Set[int] = set()
        self._under_since: Optional[float] = None

    def _agent_pids(self) -> Optional[Set[int]]:
        """Every pid in an agent tree now (never this server's own pid); None when ``ps`` could not run (unknown, not empty)."""
        procs = self._ps()
        if procs is None:
            return None
        roots = [r for r in self._roots() if r != os.getpid()]
        if not roots:
            return set()
        return set().union(*process_tree.trees(procs, roots).values()) - {os.getpid()}

    def tick(self) -> int:
        if not self.enabled:
            return 0
        figures = self._measure()
        if figures is None:
            return len(self.throttled)
        busy, line, cores = figures
        now = self._clock()
        if busy > line:
            self._under_since = None
            now_pids = self._agent_pids()
            if now_pids is None:
                return len(self.throttled)
            for pid in now_pids - self.throttled:
                if set_background(pid, True, setpriority=self._set):
                    self.throttled.add(pid)
            self.throttled &= now_pids
        elif self.throttled:
            if busy < line - CLEAR_MARGIN * cores:
                self._under_since = self._under_since if self._under_since is not None else now
                if now - self._under_since >= CLEAR_AFTER_SECONDS:
                    self.clear()
            else:
                self._under_since = None
        return len(self.throttled)

    def clear(self) -> int:
        alive = self._agent_pids()
        if alive is None:
            return 0
        cleared = sum(1 for pid in self.throttled & alive if set_background(pid, False, setpriority=self._set))
        self.throttled.clear()
        self._under_since = None
        return cleared

    def boot_clear(self) -> int:
        figures = self._measure() if self.enabled else None
        if figures is None or figures[0] > figures[1]:
            return 0
        return sum(1 for pid in self._agent_pids() or () if set_background(pid, False, setpriority=self._set))


def measure_local(wired: Any) -> Optional[Tuple[float, float, int]]:
    from src.core.machine_stats import cpu_busy
    from src.core.pack.reserve import local

    cores = os.cpu_count()
    busy = cpu_busy.METER.busy_cores(cores)["busy_1"]
    if busy is None:
        try:
            busy, _, _ = os.getloadavg()
        except OSError:
            return None
    active = local.active_reserve(wired)
    if not cores or active is None:
        return None
    return min(busy, float(cores)), cores * (1 - active["cpu_pct"] / 100), cores
