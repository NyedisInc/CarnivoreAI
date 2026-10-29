
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.swarm import memory

logger = structlog.get_logger()

KINDS = ("rebase_conflict", "merge_conflict", "push_rejected", "merge_lock_wait")
WINDOW_S = 30 * 60
THRESHOLD = 3
THROTTLED_WORKERS = 3
KEEP_S = 24 * 60 * 60

_lock = threading.Lock()


@dataclass(frozen=True)
class Throttle:

    recent: int
    lifts_at: float


def path() -> Path:
    from src.config import settings

    return Path(settings.get_state_dir()) / "swarm" / "conflicts.json"


def _load() -> Dict[str, List[Tuple[float, str]]]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("swarm_conflicts_unreadable", error_type=type(exc).__name__)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): [(float(e[0]), str(e[1])) for e in v if isinstance(e, list) and len(e) == 2] for k, v in data.items() if isinstance(v, list)}


def throttle_of(stamps: List[float], now: float) -> Optional[Throttle]:
    times = sorted(t for t in stamps if t <= now)
    if not times or now - times[-1] >= WINDOW_S:
        return None
    start = len(times) - 1
    while start > 0 and times[start] - times[start - 1] < WINDOW_S:
        start -= 1
    run = times[start:]
    if not any(run[i + THRESHOLD - 1] - run[i] < WINDOW_S for i in range(len(run) - THRESHOLD + 1)):
        return None
    return Throttle(sum(1 for t in times if now - t < WINDOW_S), times[-1] + WINDOW_S)


def current(project_id: Optional[int], now: Optional[float] = None) -> Optional[Throttle]:
    if project_id is None:
        return None
    stamp = time.time() if now is None else now
    return throttle_of([t for t, _ in _load().get(str(project_id), [])], stamp)


def record(project_id: int, kind: str, now: Optional[float] = None) -> Dict[str, object]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    stamp = time.time() if now is None else now
    with _lock:
        data = {k: [e for e in v if stamp - e[0] < KEEP_S] for k, v in _load().items()}
        data.setdefault(str(project_id), []).append((stamp, kind))
        data = {k: v for k, v in data.items() if v}
        memory.atomic_write(path(), json.dumps({k: [list(e) for e in v] for k, v in data.items()}))
    state = throttle_of([t for t, _ in data[str(project_id)]], stamp)
    recent = sum(1 for t, _ in data[str(project_id)] if stamp - t < WINDOW_S)
    logger.info("swarm_conflict_reported", project_id=project_id, kind=kind, recent=recent, throttled=state is not None)
    return {"project_id": project_id, "kind": kind, "recent": recent, "window_minutes": WINDOW_S // 60, "threshold": THRESHOLD,
            "throttled": state is not None, "limit": THROTTLED_WORKERS if state else None, "lifts_at": state.lifts_at if state else None}


def refusal(state: Throttle, workers: int, now: Optional[float] = None) -> Optional[str]:
    if workers < THROTTLED_WORKERS:
        return None
    wait = max(1, int(state.lifts_at - (time.time() if now is None else now)))
    return (f"this project's agents reported {state.recent} merge conflicts, rejected pushes or merge-lock waits in the last "
            f"{WINDOW_S // 60} minutes, so it runs at most {THROTTLED_WORKERS} agents until {WINDOW_S // 60} minutes pass with none "
            f"(retry_after {wait} s)")
