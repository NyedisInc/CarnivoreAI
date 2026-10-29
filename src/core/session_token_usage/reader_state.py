
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.session_token_usage.cache import HEAD_BYTES, CacheEntry, IncrementalCache, stat_signature
from src.core.session_token_usage.persist_spec import PersistSpec
from src.core.session_token_usage.reader_state_store import DB_NAME, ReaderStateStore, StoredRow
from src.core.test_write_guard import OutsideTempWriteError

logger = structlog.get_logger()

PERSISTED_CACHES: Tuple[Tuple[str, str], ...] = (
    ("src.core.session_token_usage.cache", "TRANSCRIPT_CACHE"),
    ("src.core.subagents.parked_launches", "_LEDGERS"),
    ("src.core.subagents.parked_launches", "_PROMPTS"),
    ("src.core.subagents.parked_launches", "_AGENT_NOTICES"),
    ("src.core.subagents.parent_index", "PARENT_INDEX_CACHE"),
    ("src.core.subagents.parent_index", "SPAWNER_INDEX_CACHE"),
    ("src.core.timers.index", "TIMER_INDEX_CACHE"),
    ("src.core.crosstalk.native_mirror", "_MIRROR_CURSORS"),
)

FLUSH_INTERVAL_S = 30.0
TAIL_BYTES = 64
MAX_PAYLOAD_BYTES = 1024 * 1024
_FAIL_LOG_EVERY_S = 600.0
_KILL_SWITCH = "CLOUDE_READER_STATE"
_STORE_ERRORS = (sqlite3.Error, OSError)


@dataclass(frozen=True)
class FlushResult:

    upserts: int = 0
    tombstones: int = 0
    failed: bool = False


@dataclass
class _Active:

    cache: IncrementalCache
    spec: PersistSpec
    version: str


class _Runtime:

    def __init__(self, store: ReaderStateStore, active: List[_Active]) -> None:
        self.store = store
        self.active = active
        self.inodes: Dict[Tuple[str, str], int] = {}
        self.stop_event = threading.Event()
        self.flush_lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.last_fail_log = 0.0


_runtime: Optional[_Runtime] = None
_runtime_lock = threading.Lock()


def effective_version(spec: PersistSpec) -> Optional[str]:
    digest = hashlib.sha256()
    for name in sorted(spec.sources):
        try:
            found = importlib.util.find_spec(name)
            if found is None or not found.origin:
                return None
            digest.update(name.encode())
            digest.update(Path(found.origin).read_bytes())
        except (ImportError, ValueError, OSError):
            return None
    return f"{spec.manual_version}:{digest.hexdigest()[:16]}"


def _read_checks(path: str, offset: int) -> Optional[Tuple[os.stat_result, bytes, bytes]]:
    """Stat a file and read its head and the bytes just before ``offset``.

    Inputs: path (str), offset (int).
    Output: (stat, head, tail) or None when the file could not be read whole;
      the tail is short only when the file is shorter than ``offset``.
    Raises FileNotFoundError when the path is gone.
    """
    with open(path, "rb") as handle:
        stat = os.fstat(handle.fileno())
        head = handle.read(HEAD_BYTES)
        start = max(0, offset - TAIL_BYTES)
        handle.seek(start)
        tail = handle.read(offset - start)
    if len(tail) != offset - max(0, offset - TAIL_BYTES):
        return None
    return stat, head, tail


def _resolve(module: str, attribute: str) -> IncrementalCache:
    cache = getattr(importlib.import_module(module), attribute)
    if not isinstance(cache, IncrementalCache) or cache.persist is None:
        raise AttributeError(f"{module}.{attribute} is not a persisted IncrementalCache")
    return cache


def _row_to_entry(row: StoredRow, spec: PersistSpec) -> CacheEntry:
    payload = json.loads(row.payload)
    return CacheEntry(size=row.size, mtime_ns=row.mtime_ns, offset=row.offset, head=row.head,
                      totals=spec.decode(payload), signature=row.sig)


def _row_still_valid(row: StoredRow) -> Optional[str]:
    try:
        stat = os.stat(row.path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "skip"
    if row.sig is not None and row.sig == stat_signature(stat):
        return None
    if stat.st_ino != row.ino or stat.st_size < max(row.size, row.offset):
        return "changed"
    try:
        checks = _read_checks(row.path, row.offset)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "skip"
    if checks is None or not checks[1].startswith(row.head) or checks[2] != row.tail:
        return "changed"
    return None


def _hydrate_one(rt: _Runtime, item: _Active) -> Dict[str, int]:
    spec = item.spec
    counts = {"loaded": 0, "dropped_missing": 0, "dropped_changed": 0, "dropped_undecodable": 0}
    rows = rt.store.load(spec.name, item.version, item.cache.max_entries)
    entries: List[Tuple[str, CacheEntry]] = []
    dead: List[Tuple[str, str]] = []
    for row in rows:
        verdict = _row_still_valid(row)
        if verdict == "skip":
            continue
        if verdict is not None:
            counts[f"dropped_{verdict}"] += 1
            dead.append((spec.name, row.path))
            continue
        try:
            entries.append((row.path, _row_to_entry(row, spec)))
        except (ValueError, TypeError, KeyError):
            counts["dropped_undecodable"] += 1
            dead.append((spec.name, row.path))
            continue
        rt.inodes[(spec.name, row.path)] = row.ino
    if dead:
        rt.store.write([], dead)
    counts["loaded"] = item.cache.hydrate(entries)
    return counts


def _open_store(state_dir: Path, names: List[str]) -> Optional[ReaderStateStore]:
    store = ReaderStateStore(state_dir / DB_NAME)
    for attempt in (1, 2):
        try:
            store.drop_readers_except(names)
            return store
        except sqlite3.DatabaseError as exc:
            logger.warning("reader_state_store_reset", error_type=type(exc).__name__,
                           attempt=attempt)
            try:
                store.reset_files()
            except OSError as os_exc:
                logger.warning("reader_state_store_reset_failed", error_type=type(os_exc).__name__)
                return None
        except OSError as exc:
            logger.warning("reader_state_store_unavailable", error_type=type(exc).__name__)
            return None
    return None


def install(state_dir: Path) -> None:
    global _runtime
    if os.environ.get(_KILL_SWITCH, "").strip().lower() == "off":
        logger.info("reader_state_disabled")
        return
    started = time.monotonic()
    try:
        with _runtime_lock:
            if _runtime is not None:
                return
            active: List[_Active] = []
            for module, attr in PERSISTED_CACHES:
                try:
                    cache = _resolve(module, attr)
                except (ImportError, AttributeError) as exc:
                    logger.error("reader_state_cache_unresolved", cache=f"{module}.{attr}",
                                 error_type=type(exc).__name__)
                    continue
                spec = cache.persist
                assert spec is not None
                version = effective_version(spec)
                if version is None:
                    logger.warning("reader_state_source_unreadable", reader=spec.name)
                    continue
                active.append(_Active(cache, spec, version))
            store = _open_store(Path(state_dir), [item.spec.name for item in active])
            if store is None:
                return
            rt = _Runtime(store, active)
            report: Dict[str, Dict[str, int]] = {}
            for item in active:
                report[item.spec.name] = _hydrate_one(rt, item)
            for item in active:
                item.cache.track_dirty(True)
            rt.thread = threading.Thread(target=_flush_loop, args=(rt,), name="reader-state-flush",
                                         daemon=True)
            _runtime = rt
            rt.thread.start()
        logger.info("reader_state_hydrated", readers=report,
                    ms=round((time.monotonic() - started) * 1000, 1))
    except OutsideTempWriteError as exc:
        logger.warning("reader_state_refused_by_test_guard", error=str(exc))
    except _STORE_ERRORS as exc:
        logger.warning("reader_state_install_failed", error_type=type(exc).__name__)


def _flush_loop(rt: _Runtime) -> None:
    while not rt.stop_event.wait(FLUSH_INTERVAL_S):
        flush_now()


def _build_rows(rt: _Runtime, item: _Active, drained: Dict[str, Optional[CacheEntry]]
                ) -> Tuple[List[StoredRow], List[Tuple[str, str]]]:
    name = item.spec.name
    upserts: List[StoredRow] = []
    tombstones: List[Tuple[str, str]] = []
    for path, entry in drained.items():
        if entry is None:
            tombstones.append((name, path))
            continue
        try:
            checks = _read_checks(path, entry.offset)
        except FileNotFoundError:
            tombstones.append((name, path))
            continue
        except OSError:
            continue
        known = rt.inodes.get((name, path))
        if (checks is None or (known is not None and known != checks[0].st_ino)
                or checks[0].st_size < entry.size or not checks[1].startswith(entry.head)):
            tombstones.append((name, path))
            continue
        payload = json.dumps(item.spec.encode(entry.totals), separators=(",", ":"))
        if len(payload) > MAX_PAYLOAD_BYTES:
            logger.warning("reader_state_row_too_large", reader=name, bytes=len(payload))
            tombstones.append((name, path))
            continue
        upserts.append(StoredRow(name, path, item.version, entry.size, entry.mtime_ns,
                                 entry.offset, entry.head, checks[2], checks[0].st_ino,
                                 entry.signature, payload, time.time()))
    return upserts, tombstones


def flush_now() -> FlushResult:
    rt = _runtime
    if rt is None:
        return FlushResult()
    with rt.flush_lock:
        drained = [(item, item.cache.drain_dirty()) for item in rt.active]
        upserts: List[StoredRow] = []
        tombstones: List[Tuple[str, str]] = []
        try:
            for item, changes in drained:
                up, dead = _build_rows(rt, item, changes)
                upserts += up
                tombstones += dead
            rt.store.write(upserts, tombstones)
        except (sqlite3.Error, OSError, OutsideTempWriteError) as exc:
            for item, changes in drained:
                item.cache.requeue(changes)
            now = time.monotonic()
            if now - rt.last_fail_log >= _FAIL_LOG_EVERY_S or rt.last_fail_log == 0.0:
                rt.last_fail_log = now
                logger.warning("reader_state_flush_failed", error_type=type(exc).__name__)
            return FlushResult(failed=True)
        for row in upserts:
            rt.inodes[(row.reader, row.path)] = row.ino
        for key in tombstones:
            rt.inodes.pop(key, None)
        return FlushResult(upserts=len(upserts), tombstones=len(tombstones))


def stop(timeout_s: float = 5.0) -> None:
    global _runtime
    with _runtime_lock:
        rt = _runtime
        if rt is None:
            return
        rt.stop_event.set()
        if rt.thread is not None:
            rt.thread.join(timeout_s)
        flush_now()
        for item in rt.active:
            item.cache.track_dirty(False)
        rt.store.close()
        _runtime = None
