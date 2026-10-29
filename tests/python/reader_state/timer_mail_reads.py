
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.core.crosstalk import native_mirror
from src.core.timers import index as timers_index
from tests.python.reader_state import fixture_tree

TIMERS, MIRROR = "timers.timer_index", "crosstalk.native_mirror"
NAMES = (TIMERS, MIRROR)


def _digest(value: Any) -> str:
    def plain(item: Any) -> Any:
        return item.isoformat() if isinstance(item, datetime) else sorted(item)
    return hashlib.md5(json.dumps(value, sort_keys=True, default=plain).encode()).hexdigest()


def _read_timers(root: Path) -> Dict[str, Any]:
    starts: List[Tuple[str, int]] = []
    real_scan = timers_index.scan_lines

    def spy(handle: Any, index: Any) -> Any:
        starts.append((Path(handle.name).stem, handle.tell()))
        return real_scan(handle, index)

    timers_index.scan_lines = spy
    out: Dict[str, Any] = {}
    for name in fixture_tree.all_names():
        index = timers_index.read_timer_index(fixture_tree.transcript_path(root, name))
        out[name] = None if index is None else asdict(index)
    return {"md5": _digest(out), "cold_parses": sorted({n for n, off in starts if off == 0}),
            "nonempty": sum(1 for v in out.values() if v and v["calls"])}


def _read_mirror(root: Path, resolvable: Tuple[str, ...]) -> Dict[str, Any]:
    events: Dict[str, Any] = {}
    delivered: Dict[str, List[str]] = {}
    backlog: Dict[str, List[str]] = {}
    cold_reads: List[str] = []
    state = {"first": b"", "name": ""}
    real_loads = native_mirror.json.loads

    def spy(line: Any, *args: Any, **kwargs: Any) -> Any:
        if line == state["first"] and state["name"] not in cold_reads:
            cold_reads.append(state["name"])
        return real_loads(line, *args, **kwargs)

    native_mirror.json.loads = spy
    try:
        for name in fixture_tree.all_names():
            path = fixture_tree.transcript_path(root, name)
            state.update(first=path.read_bytes().split(b"\n", 1)[0] + b"\n", name=name)
            found, snapshot = native_mirror._events(path)
            events[name] = [list(item) for item in found]
            waiting = {item[0]: item for item in found}
            delivered[name] = sorted(key for key, item in waiting.items() if item[2] in resolvable)
            backlog[name] = sorted(key for key in waiting if key not in delivered[name])
            if snapshot is not None:
                native_mirror._commit_cursor(str(path), snapshot, set(backlog[name]))
    finally:
        native_mirror.json.loads = real_loads
    return {"md5": _digest(events), "events": events, "delivered": delivered, "backlog": backlog,
            "cold_reads": sorted(cold_reads), "nonempty": sum(1 for v in events.values() if v)}


def read_all(root: Path, phase: str) -> Dict[str, Dict[str, Any]]:
    resolvable = ("bob",) if phase == "phase1" else ("bob", fixture_tree.LATE)
    return {TIMERS: _read_timers(root), MIRROR: _read_mirror(root, resolvable)}
