
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Optional

import structlog

from src.core.db import DatastoreError

logger = structlog.get_logger()

TTL_SECONDS = 60.0

_PACK_SQL = """
SELECT EXISTS (SELECT 1 FROM computer_links)
    OR EXISTS (SELECT 1 FROM project_replicas)
    OR EXISTS (SELECT 1 FROM hosts WHERE kind = 'peer')
    OR EXISTS (SELECT 1 FROM projects WHERE pack_state = 'replica')
    OR EXISTS (SELECT 1 FROM pack_spawn_queue WHERE state = 'queued')
    OR EXISTS (SELECT 1 FROM pack_migrations WHERE state IN ('planned', 'applying', 'verifying'))
    OR EXISTS (SELECT 1 FROM pack_migrations m JOIN projects p ON p.uid = m.subject_uid
               WHERE m.role = 'source' AND m.state = 'flipped' AND p.pack_state = 'moved_away')
"""
_MESSAGING_SQL = "SELECT EXISTS (SELECT 1 FROM messaging_providers)"


def _ask(sql: str) -> bool:
    from src.config import settings
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        return bool(conn.execute(sql).fetchone()[0])


def _probe_pack() -> bool:
    return _ask(_PACK_SQL)


def _probe_messaging() -> bool:
    return _ask(_MESSAGING_SQL)


def _probe_ai() -> bool:
    from src.config import settings
    from src.config.byoai import BYOAI_KEY
    from src.core import config_writer

    try:
        document = config_writer.read_config(Path(settings.auth_config_file).expanduser())
    except FileNotFoundError:
        return False
    block = document.get(BYOAI_KEY)
    return bool(isinstance(block, dict) and block.get("connections"))


class _Signal:

    def __init__(self, key: str, probe: Callable[[], bool]) -> None:
        self.key = key
        self._probe = probe
        self._lock = threading.Lock()
        self._value = True
        self._stamp: Optional[float] = None
        self._generation = 0
        self._failing = False

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._stamp = None

    def read(self) -> bool:
        with self._lock:
            if self._stamp is not None and time.monotonic() - self._stamp < TTL_SECONDS:
                return self._value
            generation = self._generation
        try:
            value, failed = self._probe(), False
        except (sqlite3.Error, DatastoreError, OSError, ValueError) as exc:
            value, failed = True, True
            if not self._failing:
                logger.warning("mcp_family_signal_unreadable", family=self.key, error=type(exc).__name__)
        with self._lock:
            self._failing = failed
            if generation == self._generation:
                self._value, self._stamp = value, time.monotonic()
        return value


_SIGNALS: Dict[str, _Signal] = {
    "pack": _Signal("pack", _probe_pack),
    "messaging": _Signal("messaging", _probe_messaging),
    "ai": _Signal("ai", _probe_ai),
}
_listener_lock = threading.Lock()
_ai_listener_added = False


def _on_byoai_change(_revision: int) -> None:
    invalidate("ai")


def _listen_to_ai_writes() -> None:
    global _ai_listener_added
    with _listener_lock:
        if _ai_listener_added:
            return
        from src.core.byoai import store as byoai_store

        byoai_store.add_change_listener(_on_byoai_change)
        _ai_listener_added = True


def in_use(key: str) -> bool:
    if key == "ai":
        _listen_to_ai_writes()
    return _SIGNALS[key].read()


def invalidate(key: Optional[str] = None) -> None:
    for name, signal in _SIGNALS.items():
        if key is None or key == name:
            signal.invalidate()
