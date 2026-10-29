from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set

import structlog

from src.core.stats.batch_store import BatchStore

logger = structlog.get_logger()

LEDGER_VERSION = 1
FRESH_SECONDS = 60.0
RETRY_SECONDS = 15.0
MAX_ROWS = 512
MAX_BYTES = 32 * 1024 * 1024
BEHIND_CONVERSATIONS = 8
WRITE_BUSY_MS = 1000
TOUCH_FLUSH = 64

STATE_OK, STATE_BEHIND, STATE_UNKNOWN = "ok", "behind", "unknown"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS stats_answers ("
    "key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, window_end INTEGER NOT NULL, computed_at REAL NOT NULL, "
    "last_read REAL NOT NULL, size INTEGER NOT NULL, payload BLOB NOT NULL, fail_reason TEXT, fail_at REAL)",
    "CREATE INDEX IF NOT EXISTS stats_answers_lru ON stats_answers(last_read)",
)

Compute = Callable[[Any, float], dict]

_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stats-ledger-writer")
_RECOMPUTE = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stats-ledger-recompute")


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def base_fingerprint(view: Any) -> str:
    held = view.fingerprints.get("base")
    if held is None:
        db = view.connect(readonly=True)
        enabled = db.execute("SELECT enabled FROM stats_settings WHERE singleton=1").fetchone()
        spans = db.execute("SELECT start_ts,end_ts FROM stats_disabled_spans ORDER BY start_ts").fetchall()
        prices = db.execute("SELECT version,source,source_date FROM price_versions ORDER BY version").fetchall()
        held = view.fingerprints["base"] = digest(
            LEDGER_VERSION, enabled[0] if enabled else None, [tuple(r) for r in spans], [tuple(r) for r in prices])
    return held


@dataclass
class Row:

    fingerprint: str
    window_end: int
    computed_at: float
    payload: dict
    fail_reason: Optional[str]
    fail_at: Optional[float]


def _served(payload: dict, as_of: float, stale: bool, reason: Optional[str]) -> dict:
    return {"ok": True, "result": payload, "answer": {"as_of": _iso(as_of), "stale": stale, "reason": reason}}


class _Ledger:

    def __init__(self, store: Any) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._inflight: Set[str] = set()
        self._failed_at: Dict[str, float] = {}
        self._touched: Dict[str, float] = {}
        self._inode: Optional[int] = None

    def read(self, view: Any, key: str) -> Optional[Row]:
        try:
            got = view.connect(readonly=True).execute(
                "SELECT fingerprint,window_end,computed_at,payload,fail_reason,fail_at FROM stats_answers WHERE key=?",
                (key,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                logger.warning("stats_answers_read_failed", error=str(exc)[:120])
            return None
        if got is None:
            return None
        try:
            payload = json.loads(zlib.decompress(got[3]))
        except (zlib.error, ValueError) as exc:
            logger.warning("stats_answers_row_unreadable", error=type(exc).__name__)
            return None
        with self._lock:
            self._touched[key] = _now()
        return Row(got[0], int(got[1]), float(got[2]), payload, got[4], got[5])

    def state(self) -> str:
        from src.core.stats.plugin import progress

        try:
            inode = os.stat(self.store.db_path).st_ino
        except OSError:
            return STATE_UNKNOWN
        with self._lock:
            swapped = self._inode is not None and inode != self._inode
            self._inode = inode
        if swapped:
            progress.forget(self.store.state_dir)
        found = progress.cached_progress(self.store.state_dir, block=False)
        if found is None:
            return STATE_UNKNOWN
        return STATE_BEHIND if found["pending_sources"] > BEHIND_CONVERSATIONS else STATE_OK

    def store_later(self, key: str, fingerprint: str, window_end: int, payload: dict, computed_at: float) -> None:
        blob = zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 1)
        _WRITER.submit(self._write, key, fingerprint, window_end, blob, computed_at)

    def _connect(self) -> sqlite3.Connection:
        conn = self.store.connect()
        conn.isolation_level = None
        conn.execute(f"PRAGMA busy_timeout={WRITE_BUSY_MS}")
        return conn

    def _write(self, key: str, fingerprint: str, window_end: int, blob: bytes, computed_at: float) -> None:
        with self._lock:
            pending = list(self._touched.items())
            touched, self._touched = dict(pending[:TOUCH_FLUSH]), dict(pending[TOUCH_FLUSH:])
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for ddl in _SCHEMA:
                        conn.execute(ddl)
                    conn.execute(
                        "INSERT OR REPLACE INTO stats_answers VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                        (key, fingerprint, window_end, computed_at, computed_at, len(blob), blob))
                    conn.executemany("UPDATE stats_answers SET last_read=? WHERE key=?",
                                     [(at, k) for k, at in touched.items()])
                    self._evict(conn, key)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        except (sqlite3.Error, OSError) as exc:
            logger.debug("stats_answers_write_skipped", error=str(exc)[:120])
            with self._lock:
                for k, at in touched.items():
                    self._touched.setdefault(k, at)

    @staticmethod
    def _evict(conn: sqlite3.Connection, keep: str) -> None:
        count, total = conn.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM stats_answers").fetchone()
        if count <= MAX_ROWS and total <= MAX_BYTES:
            return
        doomed = []
        for k, size in conn.execute("SELECT key,size FROM stats_answers WHERE key!=? ORDER BY last_read", (keep,)):
            if count <= MAX_ROWS and total <= MAX_BYTES:
                break
            doomed.append((k,))
            count, total = count - 1, total - size
        conn.executemany("DELETE FROM stats_answers WHERE key=?", doomed)

    def _mark_failed(self, key: str, reason: str, at: float) -> None:
        try:
            with self._connect() as conn:
                conn.execute("UPDATE stats_answers SET fail_reason=?,fail_at=? WHERE key=?", (reason, at, key))
        except sqlite3.Error as exc:
            logger.debug("stats_answers_mark_skipped", error=str(exc)[:120])

    def purge(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM stats_answers")
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise

    def refresh_later(self, key: str, fingerprint: str, window_end: int, compute: Compute, budget: float) -> None:
        with self._lock:
            if key in self._inflight or _now() - self._failed_at.get(key, 0.0) < RETRY_SECONDS:
                return
            self._inflight.add(key)
        _RECOMPUTE.submit(self._recompute, key, fingerprint, window_end, compute, budget)

    def _recompute(self, key: str, fingerprint: str, window_end: int, compute: Compute, budget: float) -> None:
        view = BatchStore(self.store)
        try:
            payload = compute(view, time.monotonic() + budget)
        except Exception as exc:  # noqa: BLE001
            now = _now()
            with self._lock:
                self._failed_at[key] = now
            logger.warning("stats_answers_recompute_failed", error=type(exc).__name__, detail=str(exc)[:120])
            _WRITER.submit(self._mark_failed, key, type(exc).__name__, now)
        else:
            if self.state() == STATE_OK:
                self.store_later(key, fingerprint, window_end, payload, _now())
        finally:
            view.release()
            with self._lock:
                self._inflight.discard(key)


_registry_lock = threading.Lock()
_registry: Dict[str, _Ledger] = {}


def ledger_for(store: Any) -> _Ledger:
    base = getattr(store, "base", store)
    key = str(base.db_path)
    with _registry_lock:
        if key not in _registry:
            _registry[key] = _Ledger(base)
        return _registry[key]


def plugin_state(store: Any) -> str:
    return ledger_for(store).state()


def serve(view: Any, *, key: str, window_end: int, fingerprint: str, state: str, compute: Compute,
          deadline: float, budget: float) -> dict:
    ledger = ledger_for(view)
    now = _now()
    row = ledger.read(view, key)
    if row is not None and state == STATE_BEHIND:
        return _served(row.payload, row.computed_at, True, "rebuilding")
    if row is not None and row.fingerprint == fingerprint:
        if (row.window_end == window_end and now - row.computed_at < FRESH_SECONDS
                and row.payload.get("revision") in (None, view.revision())):
            return _served(row.payload, row.computed_at, False, None)
        if state == STATE_OK:
            ledger.refresh_later(key, fingerprint, window_end, compute, budget)
        failing = row.fail_at is not None and row.fail_at >= row.computed_at
        return _served(row.payload, row.computed_at, True, "compute_failed" if failing else "refreshing")
    try:
        payload = compute(view, deadline)
    except (ValueError, KeyError, sqlite3.Error) as exc:
        if row is None:
            raise
        logger.warning("stats_answers_compute_failed", error=type(exc).__name__, detail=str(exc)[:120])
        return _served(row.payload, row.computed_at, True, "compute_failed")
    if state == STATE_OK:
        ledger.store_later(key, fingerprint, window_end, payload, now)
    return _served(payload, now, False, "catching_up" if state == STATE_BEHIND else None)


def purge(store: Any) -> None:
    ledger_for(store).purge()


def wait_idle(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    for pool in (_RECOMPUTE, _WRITER, _RECOMPUTE, _WRITER):
        pool.submit(lambda: None).result(max(0.0, deadline - time.monotonic()))
