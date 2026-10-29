
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Executor
from pathlib import Path
from typing import Any, Callable, Dict, Set

import structlog

from src.core.companies import hero_images

logger = structlog.get_logger()


def read_fail(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_fail(path: Path, attempts: int, reason: str, *, log_event: str) -> None:
    try:
        hero_images.atomic_write(path, json.dumps({"attempts": attempts, "at": time.time(), "reason": reason}).encode())
    except OSError as exc:
        logger.warning(log_event, error=type(exc).__name__)


def release(inflight: Set[str], lock: threading.Lock, key: str) -> None:
    with lock:
        inflight.discard(key)


def submit_once(pool: Executor, inflight: Set[str], lock: threading.Lock, key: str, job: Callable[..., Any], *args: Any) -> bool:
    with lock:
        if key in inflight:
            return False
        inflight.add(key)
    try:
        pool.submit(job, *args)
    except RuntimeError:
        release(inflight, lock, key)
        return False
    return True


def retry_due(note: Dict[str, Any], *, max_jobs: int, retry_after: float) -> bool:
    if not note:
        return True
    return int(note.get("attempts", 0)) < max_jobs and time.time() - float(note.get("at", 0)) > retry_after
