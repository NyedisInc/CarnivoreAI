
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import structlog

logger = structlog.get_logger()

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS budget_holds ("
    " item_id TEXT NOT NULL, session_key TEXT NOT NULL, item_name TEXT NOT NULL,"
    " tenant_id TEXT NOT NULL DEFAULT '', set_at REAL NOT NULL,"
    " PRIMARY KEY (item_id, session_key))"
)


def default_db_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    return settings.get_state_dir() / "argent.db"


class HoldStore:

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._mirror: Optional[Dict[str, Dict[str, str]]] = None

    def _connect(self) -> sqlite3.Connection:
        path = self._path or default_db_path()
        conn = sqlite3.connect(str(path), timeout=5)
        conn.execute(_SCHEMA)
        return conn

    def _loaded(self) -> Dict[str, Dict[str, str]]:
        if self._mirror is not None:
            return self._mirror
        mirror: Dict[str, Dict[str, str]] = {}
        try:
            conn = self._connect()
            try:
                for item_id, key, name in conn.execute("SELECT item_id, session_key, item_name FROM budget_holds"):
                    mirror.setdefault(key, {})[item_id] = name
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("budget_hold_store_unreadable", error=str(exc))
            return {}
        self._mirror = mirror
        return mirror

    def any_hold(self) -> bool:
        with self._lock:
            return bool(self._loaded())

    def holds_for(self, session_key: str) -> List[tuple]:
        with self._lock:
            return sorted(self._loaded().get(session_key, {}).items())

    def snapshot(self) -> List[dict]:
        with self._lock:
            items: Dict[str, dict] = {}
            for key, held in self._loaded().items():
                for item_id, name in held.items():
                    items.setdefault(item_id, {"item_id": item_id, "item_name": name, "session_keys": []})["session_keys"].append(key)
            return sorted(items.values(), key=lambda row: row["item_id"])

    def set_hold(self, item_id: str, item_name: str, session_keys: Iterable[str], tenant_id: str = "") -> None:
        keys = sorted({str(k) for k in session_keys})
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("DELETE FROM budget_holds WHERE item_id = ?", (item_id,))
                    conn.executemany("INSERT INTO budget_holds VALUES (?, ?, ?, ?, ?)",
                                     [(item_id, k, item_name, tenant_id, now) for k in keys])
            finally:
                conn.close()
            self._mirror = None
            self._loaded()
        self._notify()

    def clear_hold(self, item_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("DELETE FROM budget_holds WHERE item_id = ?", (item_id,))
            finally:
                conn.close()
            self._mirror = None
            self._loaded()
        self._notify()

    def reload(self) -> None:
        with self._lock:
            self._mirror = None

    @staticmethod
    def _notify() -> None:
        from src.core import resource_push  # noqa: PLC0415
        from src.core.resource_push import topics  # noqa: PLC0415

        resource_push.notify(topics.ARGENT_HOLDS)


STORE = HoldStore()
