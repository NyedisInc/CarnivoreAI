
from __future__ import annotations

import subprocess
import threading
import time
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from src.core import libproc_snapshot


class Proc(NamedTuple):

    pid: int
    ppid: int
    cpu: float
    rss_kb: int


def parse(text: str) -> List[Proc]:
    rows: List[Proc] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        try:
            rows.append(Proc(int(parts[0]), int(parts[1]), float(parts[2]), int(parts[3])))
        except ValueError:
            continue
    return rows


_BASELINE_MAX_AGE: float = 120.0
_BASELINE_MIN_WINDOW: float = 2.0
_baseline_lock = threading.Lock()
_baseline: Optional[Tuple[float, Dict[int, int]]] = None
_window_cpu: Dict[int, float] = {}


def _read_libproc() -> Optional[List[Proc]]:
    global _baseline, _window_cpu
    now = time.monotonic()
    table = libproc_snapshot.task_table()
    if table is None:
        return None
    with _baseline_lock:
        prev = _baseline
        if prev is None or now - prev[0] >= _BASELINE_MAX_AGE:
            _baseline, _window_cpu = (now, {r.pid: r.cpu_ns for r in table}), {}
            return None
        if now - prev[0] >= _BASELINE_MIN_WINDOW:
            wall_ns = (now - prev[0]) * 1e9
            _window_cpu = {r.pid: max(0.0, (r.cpu_ns - prev[1].get(r.pid, 0)) / wall_ns * 100.0) for r in table}
            _baseline = (now, {r.pid: r.cpu_ns for r in table})
        if not _window_cpu:
            return None
        cpu = _window_cpu
    return [Proc(r.pid, r.ppid, cpu.get(r.pid, 0.0), r.rss_kb) for r in table]


def read() -> Optional[List[Proc]]:
    rows = _read_libproc()
    if rows:
        return rows
    try:
        done = subprocess.run(["ps", "-o", "pid=,ppid=,%cpu=,rss=", "-ax"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse(done.stdout) if done.returncode == 0 else None


def trees(procs: Iterable[Proc], roots: Iterable[int]) -> Dict[int, Set[int]]:
    children: Dict[int, List[int]] = {}
    present: Set[int] = set()
    for p in procs:
        children.setdefault(p.ppid, []).append(p.pid)
        present.add(p.pid)
    out: Dict[int, Set[int]] = {}
    for root in roots:
        if root not in present:
            continue
        seen, stack = {root}, [root]
        while stack:
            for child in children.get(stack.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        out[root] = seen
    return out
