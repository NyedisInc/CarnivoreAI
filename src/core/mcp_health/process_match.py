
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.background_work.listing import SNAPSHOT_MARK
from src.core.mcp_health.servers import ServerSpec

MAX_DEPTH: int = 4


def required_tokens(spec: ServerSpec) -> Tuple[str, ...]:
    return tuple(a for a in spec.args if a and not a.startswith("-") and "${" not in a)


def _basename(token: str) -> str:
    return os.path.basename(token.rstrip("/"))


def matches(spec: ServerSpec, command: str) -> bool:
    tokens = command.split()
    if not tokens:
        return False
    need = required_tokens(spec)
    if need:
        have = set(tokens) | {_basename(t) for t in tokens}
        return all((t in command) if any(c.isspace() for c in t) else (t in have or _basename(t) in have)
                   for t in need)
    if not spec.command or "${" in spec.command:
        return False
    want = _basename(spec.command)
    return any(_basename(t) == want for t in tokens[:2])


def descendants(
    children: Dict[int, List[int]], root: int, commands: Dict[int, str], max_depth: int = MAX_DEPTH
) -> List[int]:
    out: List[int] = []
    frontier = [root]
    seen = {root}
    for _ in range(max_depth):
        nxt: List[int] = []
        for pid in frontier:
            for child in children.get(pid, ()):
                if child not in seen and SNAPSHOT_MARK not in commands.get(child, ""):
                    seen.add(child)
                    out.append(child)
                    nxt.append(child)
        frontier = nxt
    return out


def alive(spec: ServerSpec, agent_pid: int, commands: Dict[int, str], children: Dict[int, List[int]]) -> Optional[bool]:
    if agent_pid not in commands:
        return None
    return any(matches(spec, commands.get(pid, "")) for pid in descendants(children, agent_pid, commands))


def index_children(parents: Iterable[Tuple[int, int]]) -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = {}
    for pid, ppid in parents:
        out.setdefault(ppid, []).append(pid)
    return out
