
from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import structlog

from src.cplugs.sdk import old_names as sdk
from src.core.mcp_usage import store as usage_store

logger = structlog.get_logger()

Key = Tuple[str, str, str, str]
_pending: "Counter[Key]" = Counter()
_lock = threading.Lock()


def record(kind: str, name: str, via: str, caller: str = "", now: Optional[datetime] = None) -> None:
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    with _lock:
        _pending[(day, str(kind), str(name), str(via))] += 1
    logger.info("old_name_used", kind=kind, name=name, via=via, caller=caller)


def install() -> None:
    sdk.install_sink(record)


def flush(store: Optional[usage_store.UsageStore] = None) -> int:
    with _lock:
        taken = dict(_pending)
        _pending.clear()
    if not taken:
        return 0
    try:
        (store or usage_store.get_store()).add_old_names([(*key, calls) for key, calls in taken.items()])
    except (sqlite3.Error, OSError, RuntimeError):
        with _lock:
            for key, calls in taken.items():
                _pending[key] += calls
        raise
    return sum(taken.values())


def waiting() -> Dict[Key, int]:
    with _lock:
        return dict(_pending)
