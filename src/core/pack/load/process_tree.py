
from __future__ import annotations

import subprocess
from typing import Dict, Iterable, List, NamedTuple, Optional, Set


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


def read() -> Optional[List[Proc]]:
    """Every process now, or None when ``ps`` could not run (never an empty list for a failure). Blocking."""
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
