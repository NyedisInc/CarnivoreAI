
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from src.core.pipeline import contract as C
from src.core.pipeline.observe import DirtyView

STATE_CAUGHT_UP: str = "caught_up"
STATE_BEHIND: str = "behind"
STATE_STALLED: str = "stalled"
STATE_REBUILDING: str = "rebuilding"

STALL_AFTER_SECONDS: float = 300.0


@dataclass(frozen=True)
class Snapshot:

    now: float
    wall: float
    view: DirtyView
    in_flight: int
    last_progress: float
    last_delivery_wall: Optional[float]
    plugins: Sequence[C.Plugin]
    rebuilding: Sequence[str] = ()
    scan: Optional[Dict[str, Any]] = None
    threads: Dict[str, bool] = field(default_factory=dict)
    recent: Sequence[Dict[str, Any]] = ()
    tallies: Mapping[str, Tuple[Optional[float], int]] = field(default_factory=dict)
    running: Sequence[Dict[str, Any]] = ()
    queue: Mapping[str, Any] = field(default_factory=lambda: {"items": [], "total": 0})


@dataclass
class PluginTally:

    last_delivery_at: Optional[float] = None
    runs: int = 0


def _lag(count: int, oldest: Optional[float], now: float) -> Dict[str, Any]:
    return {"files": count, "seconds": round(max(0.0, now - oldest), 1) if oldest is not None and count else 0.0}


def build(s: Snapshot) -> Dict[str, Any]:
    pending = s.view.pending + s.in_flight
    oldest = s.view.oldest_first_dirty
    since = max(s.last_progress, oldest if oldest is not None else s.last_progress)
    stalled = pending > 0 and s.now - since > STALL_AFTER_SECONDS
    if stalled:
        state = STATE_STALLED
    elif s.rebuilding:
        state = STATE_REBUILDING
    elif pending:
        state = STATE_BEHIND
    else:
        state = STATE_CAUGHT_UP
    plugins: Dict[str, Any] = {}
    for plugin in s.plugins:
        files = sum(n for fam, (n, _) in s.view.by_family.items() if plugin.reads(fam))
        first = min((t for fam, (_, t) in s.view.by_family.items() if plugin.reads(fam)), default=None)
        failing = [f for f in s.view.failing.values() if plugin.id in f.plugins]
        newest = max(failing, key=lambda f: f.retry_at, default=None)
        delivered_at, runs = s.tallies.get(plugin.id, (None, 0))
        plugins[plugin.id] = {"lag": _lag(files, first, s.now), "failures": len(failing),
                              "last_error": newest.error if newest else None,
                              "rebuilding": plugin.id in s.rebuilding,
                              "last_delivery_at": delivered_at, "runs": runs}
    return {
        "state": state,
        "lag": _lag(pending, oldest, s.now),
        "last_delivery_at": s.last_delivery_wall,
        "last_delivery_age": None if s.last_delivery_wall is None else round(max(0.0, s.wall - s.last_delivery_wall), 1),
        "stalled_since": round(s.wall - (s.now - since), 3) if stalled else None,
        "rebuilding": list(s.rebuilding),
        "parked_files": len(s.view.failing),
        "plugins": plugins,
        "scan": s.scan,
        "threads": dict(s.threads),
        "recent": [dict(row) for row in s.recent],
        "running": [dict(row) for row in s.running],
        "queue": {"items": [dict(item) for item in s.queue.get("items", ())], "total": int(s.queue.get("total", 0))},
    }
