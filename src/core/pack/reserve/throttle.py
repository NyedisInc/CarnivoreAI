
from __future__ import annotations

import os
import sqlite3
import sys
import time
from contextlib import closing
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.machine_stats import libproc_snapshot
from src.core.pack.load import process_tree
from src.core.tmux_transport.run import tmux_argv_stdout
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

PRIO_DARWIN_PROCESS = 4
PRIO_DARWIN_BG = 0x1000
TICK_SECONDS = 10.0
CLEAR_AFTER_SECONDS = 60.0
CLEAR_MARGIN = 0.05

SetPriority = Callable[[int, int, int], None]
Select = Callable[[List[process_tree.Proc]], Optional[Tuple[Set[int], Set[int]]]]
StartOf = Callable[[Iterable[int]], Optional[Dict[int, str]]]
Viewing = Callable[[Set[str]], Set[str]]
_AGENT_SESSIONS_SQL = ("SELECT s.tmux_socket, s.tmux_name FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
                       "JOIN swarm_wakes w ON w.agent_id = a.id AND w.ended_at IS NULL "
                       "WHERE a.torn_down_at IS NULL AND s.tmux_name IS NOT NULL AND s.origin != 'peer' "
                       "UNION SELECT s.tmux_socket, s.tmux_name FROM swarm_remote_bodies b JOIN sessions s ON s.id = b.session_row_id "
                       "WHERE b.torn_down_at IS NULL AND s.tmux_name IS NOT NULL AND s.origin != 'peer'")


ArgvOf = Callable[[Set[int]], Optional[Mapping[int, Tuple[str, ...]]]]


def _real_argv(pids: Set[int]) -> Optional[Dict[int, Tuple[str, ...]]]:
    details = libproc_snapshot.process_details(pids) if pids else {}
    return None if details is None else {p: d.argv for p, d in details.items()}


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


def agent_panes(open_db: Callable[[], sqlite3.Connection], *, run: Optional[Callable[[List[str]], Optional[str]]] = None,
                viewing: Optional[Viewing] = None) -> Tuple[List[int], List[int]]:
    with closing(open_db()) as conn:
        wanted: Dict[str, Set[str]] = {}
        for socket, name in conn.execute(_AGENT_SESSIONS_SQL):
            wanted.setdefault(str(socket), set()).add(str(name))
    reader = run or tmux_argv_stdout
    seen: List[Tuple[str, int, bool]] = []
    for socket, names in wanted.items():
        try:
            argv = tmux_argv_prefix(socket)
        except TmuxVersionSkewError:
            continue
        out = reader(argv + ["list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}\t#{session_attached}"])
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] in names and parts[1].isdigit():
                seen.append((parts[0], int(parts[1]), parts[2] != "0"))
    watched = viewing({name for name, _, _ in seen}) if viewing is not None and seen else set()
    loose = [pid for name, pid, client in seen if not client and name not in watched]
    held = [pid for name, pid, client in seen if client or name in watched]
    return loose, held


class Throttle:

    def __init__(self, *, measure: Callable[[], Optional[Tuple[float, float, int]]], roots: Callable[[], List[int]],
                 ps: Callable[[], Optional[List[process_tree.Proc]]] = process_tree.read, setpriority: Optional[SetPriority] = None,
                 clock: Callable[[], float] = time.monotonic, enabled: Optional[bool] = None, select: Optional[Select] = None,
                 exempt: Optional[Callable[[], List[int]]] = None, start_of: StartOf = libproc_snapshot.start_text,
                 argv_of: ArgvOf = _real_argv) -> None:
        self._measure, self._roots, self._ps, self._set, self._clock, self._select = measure, roots, ps, setpriority, clock, select
        self._exempt, self._start_of, self._argv_of = exempt, start_of, argv_of
        self.enabled = sys.platform == "darwin" if enabled is None else enabled
        self.throttled: Set[int] = set()
        self._started: Dict[int, str] = {}
        self._normal: Set[int] = set()
        self._under_since: Optional[float] = None

    def held_pids(self) -> FrozenSet[int]:
        return frozenset(self.throttled)

    def _agent_pids(self) -> Optional[Tuple[Set[int], Set[int], Set[int]]]:
        procs = self._ps()
        if procs is None:
            return None
        me = os.getpid()
        if self._select is not None:
            picked = self._select(procs)
            return None if picked is None else (picked[0] - {me}, picked[1] - {me}, set())
        roots = [r for r in self._roots() if r != me]
        held = [r for r in (self._exempt() if self._exempt is not None else []) if r != me]
        found = process_tree.trees(procs, roots + held)
        loose = set().union(*(found[r] for r in roots if r in found)) - {me}
        argv = self._argv_of(loose)
        if argv is None:
            return None
        from src.core.pack.reserve.session_demote import is_agent_argv
        demote: Set[int] = set()
        for root in roots:
            tree = found.get(root, set())
            agents = {p for p in tree if is_agent_argv(argv.get(p, ()))}
            below = set().union(*process_tree.trees(procs, agents).values()) if agents else tree
            demote |= below - agents - {root}
        demote -= {me}
        scope = loose | (set().union(*(found[r] for r in held if r in found)) - {me})
        return demote, scope, scope - demote

    def _starts(self, pids: Iterable[int]) -> Dict[int, str]:
        return self._start_of(pids) or {}

    def _restore_strays(self, scope: Set[int]) -> int:
        gone = self.throttled - scope
        if not gone:
            return 0
        now = self._starts(gone)
        done = 0
        for pid in gone:
            if self._started.get(pid) is not None and now.get(pid) == self._started[pid] and set_background(pid, False, setpriority=self._set):
                done += 1
            self.throttled.discard(pid)
        return done

    def _release_attached(self) -> None:
        picked = self._agent_pids()
        if picked is None:
            return
        for pid in self.throttled & picked[2]:
            set_background(pid, False, setpriority=self._set)
        self.throttled -= picked[2]

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
            picked = self._agent_pids()
            if picked is None:
                return len(self.throttled)
            now_pids, scope, exempt = picked
            for pid in (self.throttled & scope) - now_pids:
                set_background(pid, False, setpriority=self._set)
            self._restore_strays(scope)
            fresh = now_pids - self.throttled
            starts = self._starts(fresh) if fresh else {}
            for pid in fresh:
                if set_background(pid, True, setpriority=self._set):
                    self.throttled.add(pid)
                    if pid in starts:
                        self._started[pid] = starts[pid]
            for pid in (exempt - self.throttled) - self._normal:
                set_background(pid, False, setpriority=self._set)
            self._normal = set(exempt)
            self.throttled &= now_pids
        elif self.throttled:
            self._release_attached()
            if busy < line - CLEAR_MARGIN * cores:
                self._under_since = self._under_since if self._under_since is not None else now
                if now - self._under_since >= CLEAR_AFTER_SECONDS:
                    self.clear()
            else:
                self._under_since = None
        self._started = {p: t for p, t in self._started.items() if p in self.throttled}
        return len(self.throttled)

    def clear(self) -> int:
        picked = self._agent_pids()
        if picked is None:
            return 0
        cleared = sum(1 for pid in self.throttled & picked[1] if set_background(pid, False, setpriority=self._set))
        cleared += self._restore_strays(picked[1])
        self.throttled.clear()
        self._started.clear()
        self._normal.clear()
        self._under_since = None
        return cleared

    def boot_clear(self) -> int:
        picked = self._agent_pids() if self.enabled else None
        return sum(1 for pid in (picked[1] if picked else ()) if set_background(pid, False, setpriority=self._set))


def measure_local(wired: Any, *, default_busy_fraction: Optional[float] = None) -> Optional[Tuple[float, float, int]]:
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
    if not cores or (active is None and default_busy_fraction is None):
        return None
    line = cores * default_busy_fraction if active is None else cores * (1 - active["cpu_pct"] / 100)
    return min(busy, float(cores)), line, cores
