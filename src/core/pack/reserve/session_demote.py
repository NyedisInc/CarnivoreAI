
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.machine_stats import libproc_snapshot
from src.core.pack.load import process_tree
from src.core.pack.reserve import throttle as throttle_mod
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix
from src.core.tmux_transport.run import tmux_argv_stdout

logger = structlog.get_logger()

FOCUS_SECONDS = 120.0
DEFAULT_BUSY_FRACTION = 0.75
_AGENT_NAMES = ("claude", "codex")
_SESSIONS_SQL = ("SELECT DISTINCT tmux_socket FROM sessions WHERE tmux_socket IS NOT NULL AND tmux_name IS NOT NULL "
                 "AND origin != 'peer'")

_last_input: Dict[str, float] = {}
_input_lock = threading.Lock()


def note_viewer_input(tmux_name: Optional[str], *, now: Optional[float] = None) -> None:
    if tmux_name:
        with _input_lock:
            _last_input[tmux_name] = time.monotonic() if now is None else now


def focused_sessions(*, now: Optional[float] = None, window: float = FOCUS_SECONDS) -> Set[str]:
    t = time.monotonic() if now is None else now
    with _input_lock:
        for name in [n for n, at in _last_input.items() if t - at >= window]:
            del _last_input[name]
        return set(_last_input)


def is_agent_argv(argv: Iterable[str]) -> bool:
    args = list(argv)
    if not args:
        return False
    names = [os.path.basename(a) for a in args[:2]]
    if names[0] in _AGENT_NAMES or (names[0] in ("node", "bun") and len(names) > 1 and names[1] in _AGENT_NAMES):
        return True
    return "/@openai/codex" in args[0]


def session_trees(procs: List[process_tree.Proc], panes: Mapping[str, List[int]], argv: Mapping[int, Tuple[str, ...]]) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for name, roots in panes.items():
        for root, tree in process_tree.trees(procs, roots).items():
            agents = {p for p in tree if is_agent_argv(argv.get(p, ()))}
            if not agents:
                continue
            below = set().union(*process_tree.trees(procs, agents).values())
            out.setdefault(name, set()).update(below - agents - {root})
    return out


def select_demotions(procs: List[process_tree.Proc], panes: Mapping[str, List[int]], argv: Mapping[int, Tuple[str, ...]],
                     focused: Set[str]) -> Tuple[Set[int], Set[int]]:
    scope: Set[int] = set()
    for roots in panes.values():
        for tree in process_tree.trees(procs, roots).values():
            scope |= tree
    demote: Set[int] = set()
    for name, below in session_trees(procs, panes, argv).items():
        if name not in focused:
            demote |= below
    return demote, scope


def _excluded_names(conn: sqlite3.Connection) -> Set[str]:
    rows = conn.execute(throttle_mod._AGENT_SESSIONS_SQL)
    return {str(name) for _, name in rows}


def pane_roots(open_db: Callable[[], sqlite3.Connection], *, run: Optional[Callable[[List[str]], Optional[str]]] = None) -> Dict[str, List[int]]:
    with closing(open_db()) as conn:
        sockets = [str(r[0]) for r in conn.execute(_SESSIONS_SQL)]
        skip = _excluded_names(conn)
    reader = run or tmux_argv_stdout
    panes: Dict[str, List[int]] = {}
    for socket in sockets:
        try:
            prefix = tmux_argv_prefix(socket)
        except TmuxVersionSkewError:
            continue
        for line in (reader(prefix + ["list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}"]) or "").splitlines():
            name, _, pid = line.partition("\t")
            if pid.isdigit() and name not in skip:
                panes.setdefault(name, []).append(int(pid))
    return panes


def gather(open_db: Callable[[], sqlite3.Connection], procs: List[process_tree.Proc]
           ) -> Optional[Tuple[Dict[str, List[int]], Dict[int, Tuple[str, ...]]]]:
    panes = pane_roots(open_db)
    trees = process_tree.trees(procs, [r for roots in panes.values() for r in roots])
    pids = set().union(*trees.values()) if trees else set()
    details = libproc_snapshot.process_details(pids) if pids else {}
    if details is None:
        return None
    return panes, {p: d.argv for p, d in details.items()}


def make_select(open_db: Callable[[], sqlite3.Connection]) -> throttle_mod.Select:
    def select(procs: List[process_tree.Proc]) -> Optional[Tuple[Set[int], Set[int]]]:
        got = gather(open_db, procs)
        if got is None:
            return None
        return select_demotions(procs, got[0], got[1], focused_sessions())
    return select


def build(wired: Any) -> throttle_mod.Throttle:
    return throttle_mod.Throttle(
        measure=lambda: throttle_mod.measure_local(wired, default_busy_fraction=DEFAULT_BUSY_FRACTION),
        roots=lambda: [], select=make_select(wired.open_db))
