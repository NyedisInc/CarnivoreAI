
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk import CplugContext

PHASES = ("queued", "running", "testing", "installing", "blocked", "done")
DEFAULT_WORKER = "main"
MAX_WORKER = 40
MAX_NOTE = 300
MAX_WORKERS = 8
STALE_AFTER_S = 30 * 60
DROP_AFTER_S = 6 * 60 * 60

_lines: Dict[str, Dict[int, Dict[str, dict]]] = {}
_lock = threading.Lock()


def _key(ctx: CplugContext) -> str:
    return str(ctx.storage.path)


def _prune(slot: Dict[int, Dict[str, dict]], now: float) -> None:
    for item_id in list(slot):
        for worker in [w for w, line in slot[item_id].items() if now - line["at"] > DROP_AFTER_S]:
            del slot[item_id][worker]
        if not slot[item_id]:
            del slot[item_id]


def clean(phase: Any, note: Any, worker: Any) -> Dict[str, str]:
    if phase not in PHASES:
        raise TaskManagerInvalid(f"phase must be one of {', '.join(PHASES)}")
    if note is not None and not isinstance(note, str):
        raise TaskManagerInvalid("note must be text")
    if worker is not None and not isinstance(worker, str):
        raise TaskManagerInvalid("worker must be text")
    text = " ".join((note or "").split())
    label = " ".join((worker or "").split()) or DEFAULT_WORKER
    if len(text) > MAX_NOTE:
        raise TaskManagerInvalid(f"note: over {MAX_NOTE} characters")
    if len(label) > MAX_WORKER:
        raise TaskManagerInvalid(f"worker: over {MAX_WORKER} characters")
    return {"phase": phase, "note": text, "worker": label}


def _publish(ctx: CplugContext) -> None:
    try:
        ctx.notify("progress")
    except (RuntimeError, ValueError) as exc:
        ctx.log.warning("task_manager_progress_notify_failed", error=str(exc))


def report(ctx: CplugContext, item_id: int, phase: Any, note: Any = None, worker: Any = None,
           clock: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    fields = clean(phase, note, worker)
    now = (clock or time.time)()
    with _lock:
        slot = _lines.setdefault(_key(ctx), {})
        _prune(slot, now)
        lines = slot.setdefault(item_id, {})
        if fields["worker"] not in lines and len(lines) >= MAX_WORKERS:
            raise TaskManagerInvalid(f"at most {MAX_WORKERS} workers report on one item")
        lines[fields["worker"]] = {"phase": fields["phase"], "note": fields["note"], "at": now}
    _publish(ctx)
    return {"item_id": item_id, **fields}


def snapshot(ctx: CplugContext, clock: Optional[Callable[[], float]] = None) -> Dict[str, List[dict]]:
    now = (clock or time.time)()
    with _lock:
        slot = _lines.setdefault(_key(ctx), {})
        _prune(slot, now)
        out: Dict[str, List[dict]] = {}
        for item_id, lines in slot.items():
            rows = sorted(lines.items(), key=lambda kv: kv[1]["at"], reverse=True)
            out[str(item_id)] = [
                {"worker": worker, "phase": line["phase"], "note": line["note"],
                 "age_s": int(now - line["at"]), "stale": now - line["at"] >= STALE_AFTER_S}
                for worker, line in rows]
        return out


def reset(ctx: Optional[CplugContext] = None) -> None:
    with _lock:
        if ctx is None:
            _lines.clear()
        else:
            _lines.pop(_key(ctx), None)
