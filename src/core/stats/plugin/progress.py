
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


def progress(state_dir: Path) -> Dict[str, int]:
    from src.core.db import DatastoreUnreadableError, db_path_for
    from src.core.pipeline import lag
    from src.core.stats.plugin.pipeline_plugin import STATS

    try:
        found = lag.lag_of(Path(state_dir), db_path_for(Path(state_dir)), STATS)
    except (sqlite3.Error, DatastoreUnreadableError, OSError) as exc:
        logger.warning("stats_plugin_progress_unreadable", error=type(exc).__name__)
        return {"known_sources": 0, "pending_sources": 0}
    return {"known_sources": found.files_tracked, "pending_sources": found.behind_conversations}


CACHE_MAX_AGE_S: float = 30.0
_cache_lock = threading.Lock()
_cache: Dict[str, tuple] = {}
_refreshing: set = set()


def _refresh(key: str, state_dir: Path) -> None:
    try:
        value = progress(state_dir)
        with _cache_lock:
            _cache[key] = (time.monotonic(), value)
    finally:
        with _cache_lock:
            _refreshing.discard(key)


def forget(state_dir: Path) -> None:
    """Drop the kept progress of one state directory, so the next read measures it afresh (a rebuild swapped the
    database file). Input: state_dir. Output: None."""
    from src.core.pipeline import lag

    lag.forget(Path(state_dir))
    with _cache_lock:
        _cache.pop(str(state_dir), None)


def cached_progress(state_dir: Path, *, block: bool = True) -> Optional[Dict[str, int]]:
    key = str(state_dir)
    with _cache_lock:
        held = _cache.get(key)
        refresh = held is not None and time.monotonic() - held[0] > CACHE_MAX_AGE_S and key not in _refreshing
        if refresh:
            _refreshing.add(key)
    if held is None and not block:
        with _cache_lock:
            start = key not in _refreshing
            _refreshing.add(key)
        if start:
            threading.Thread(target=_refresh, args=(key, Path(state_dir)), name="stats-progress", daemon=True).start()
        return None
    if held is None:
        value = progress(state_dir)
        with _cache_lock:
            _cache[key] = (time.monotonic(), value)
        return value
    if refresh:
        threading.Thread(target=_refresh, args=(key, Path(state_dir)), name="stats-progress", daemon=True).start()
    return held[1]
