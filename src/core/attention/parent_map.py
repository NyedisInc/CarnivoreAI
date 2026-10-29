from __future__ import annotations

from typing import Dict, List, Mapping, Set


def descendants(root_pid: int, process_parents: Mapping[int, int]) -> List[int]:
    children: Dict[int, List[int]] = {}
    for pid, ppid in process_parents.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    found: List[int] = []
    queue = list(children.get(root_pid, ()))
    seen = {root_pid}
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        found.append(pid)
        queue.extend(children.get(pid, ()))
    return found


def descends_from(pid: int, root_pid: int, parents: Mapping[int, int]) -> bool:
    visited: Set[int] = set()
    while pid > 0 and pid not in visited:
        if pid == root_pid:
            return True
        visited.add(pid)
        pid = parents.get(pid, 0)
    return False
