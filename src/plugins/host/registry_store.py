
from __future__ import annotations

import copy
import fcntl
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, TypeVar

import structlog

from src.core.db import DatastoreError, connect, db_path_for
from src.core.plugin_registry import marker as registry_marker
from src.core.safe_io import realpath_memo
from src.core.test_write_guard import assert_test_write_allowed
from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()

STATE_DIR_NAME = "cplugs"
PLUGINS_DIR_NAME = "plugins"
REGISTRY_FILE = "registry.json"
LOCK_FILE = ".plugins.lock"
BACKUP_PREFIX = "migration-backup-"

SCHEMA = 2
REGISTRY_FILE_MODE = 0o644
MARKER_BUSY_MS = 2000
MIGRATION_KEY = "migration"
MIGRATED_AT_KEY = "migrated_at"
LEDGER_COPY_KEY = "ledger_copy"
MIGRATION_VERSION = 2

STATUS_OK, STATUS_MISSING, STATUS_UNREADABLE = "ok", "missing", "unreadable"

LOCK_WAIT_SECONDS = 15.0
"""How long a writer waits for the lock before it is refused with :class:`RegistryBusy`."""
LOCK_POLL_SECONDS = 0.02

SOURCE_REGISTRY = "registry.json"
SOURCE_NONE = "none"
SOURCE_READ_ONLY = "read_only"

KIND_FEATURE = "feature"
KIND_PLUGIN = "plugin"
SOURCE_CATALOG = "catalog"
SOURCE_FOLDER = "folder"
LOCAL_PREFIX = "local/"
DEFAULT_SIDELOAD_HOURS = 12

T = TypeVar("T")


class RegistryBusy(OSError):
    pass


class RegistryUnreadable(OSError):
    pass


@dataclass
class _Frame:

    fd: int
    depth: int = 0


_proc_locks: Dict[str, threading.RLock] = {}
_proc_locks_guard = threading.Lock()
_held = threading.local()

_read_only: Dict[str, str] = {}
_guard = threading.Lock()
_cache: Dict[str, Tuple[int, int, int, int, Dict[str, Any]]] = {}
_write_listeners: List[Callable[[], None]] = []


def cplugs_dir(state_dir: Path) -> Path:
    return Path(state_dir) / STATE_DIR_NAME


def plugins_dir(state_dir: Path) -> Path:
    return Path(state_dir) / PLUGINS_DIR_NAME


def lock_path(state_dir: Path) -> Path:
    return Path(state_dir) / LOCK_FILE


def registry_path(state_dir: Path) -> Path:
    return plugins_dir(state_dir) / REGISTRY_FILE


def backup_dir(state_dir: Path, generation: int) -> Path:
    return cplugs_dir(state_dir) / f"{BACKUP_PREFIX}{generation}"


def backups_newest_first(state_dir: Path) -> List[Path]:
    root = cplugs_dir(state_dir)
    if not root.is_dir():
        return []
    found = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX)]
    return sorted(found, key=lambda p: p.stat().st_mtime_ns, reverse=True)


def _key(state_dir: Path) -> str:
    return realpath_memo.realpath(state_dir)


def set_read_only(state_dir: Path, reason: str) -> None:
    with _guard:
        _read_only[_key(state_dir)] = reason


def clear_read_only(state_dir: Path) -> None:
    with _guard:
        _read_only.pop(_key(state_dir), None)


def read_only_reason(state_dir: Path) -> Optional[str]:
    with _guard:
        return _read_only.get(_key(state_dir))


def _valid(doc: Any) -> bool:
    return (
        isinstance(doc, dict)
        and isinstance(doc.get("generation"), int)
        and not isinstance(doc.get("generation"), bool)
        and isinstance(doc.get("items"), dict)
        and isinstance(doc.get("tombstones"), dict)
        and (isinstance(doc.get("switches"), dict) if "switches" in doc else True)
        and (isinstance(doc.get("non_sidecar_sideloads"), dict) if "non_sidecar_sideloads" in doc else True)
    )


def new_document(generation: int = 1, migrated_at: Optional[str] = None) -> Dict[str, Any]:
    stamp = migrated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": SCHEMA,
        "generation": generation,
        "switches": {
            "third_party": False,
            "sideload": {"enabled_at": None, "hours": DEFAULT_SIDELOAD_HOURS, "expires_at": None},
        },
        "items": {},
        "tombstones": {},
        "non_sidecar_sideloads": {},
        MIGRATION_KEY: {"version": MIGRATION_VERSION, MIGRATED_AT_KEY: stamp},
    }


def normalize_document(doc: Mapping[str, Any], *, generation: int, migrated_at: Optional[str] = None) -> Dict[str, Any]:
    out = copy.deepcopy(dict(doc))
    stamp = migrated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["schema"] = SCHEMA
    out["generation"] = generation
    switches = out.get("switches") if isinstance(out.get("switches"), dict) else {}
    sl_switch = switches.get("sideload") if isinstance(switches.get("sideload"), dict) else {}
    out["switches"] = {
        "third_party": switches.get("third_party") is True,
        "sideload": {
            "enabled_at": sl_switch.get("enabled_at"),
            "hours": sl_switch.get("hours", DEFAULT_SIDELOAD_HOURS),
            "expires_at": sl_switch.get("expires_at"),
        },
    }
    out.setdefault("items", {})
    out.setdefault("tombstones", {})
    out.setdefault("non_sidecar_sideloads", {})
    block = out.get(MIGRATION_KEY) if isinstance(out.get(MIGRATION_KEY), dict) else {}
    out[MIGRATION_KEY] = {
        "version": MIGRATION_VERSION,
        MIGRATED_AT_KEY: block.get(MIGRATED_AT_KEY) or out.get(MIGRATED_AT_KEY) or stamp,
    }
    return out


def parse_registry(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, STATUS_MISSING
    except (OSError, ValueError) as exc:
        logger.warning("plugin_registry_unreadable", path=path.name, error_type=type(exc).__name__)
        return None, STATUS_UNREADABLE
    if not _valid(doc):
        logger.warning("plugin_registry_unreadable", path=path.name, error_type="bad_shape")
        return None, STATUS_UNREADABLE
    return doc, STATUS_OK


def load_registry(state_dir: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    path = registry_path(state_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _cache.pop(key, None)
        return None, STATUS_MISSING
    except OSError as exc:
        _cache.pop(key, None)
        logger.warning("plugin_registry_unreadable", path=path.name, error_type=type(exc).__name__)
        return None, STATUS_UNREADABLE
    signature = (info.st_ino, info.st_ctime_ns, info.st_mtime_ns, info.st_size)
    held = _cache.get(key)
    if held is not None and held[:4] == signature:
        return held[4], STATUS_OK
    doc, status = parse_registry(path)
    if doc is None:
        _cache.pop(key, None)
        return None, status
    _cache[key] = (*signature, doc)
    return doc, STATUS_OK


def load_document(state_dir: Path) -> Optional[Dict[str, Any]]:
    doc, status = load_registry(state_dir)
    return doc if status == STATUS_OK else None


def is_migrated(doc: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(doc, Mapping):
        return False
    schema = doc.get("schema")
    block = doc.get(MIGRATION_KEY)
    version = block.get("version") if isinstance(block, Mapping) else None
    return (
        isinstance(schema, int)
        and not isinstance(schema, bool)
        and schema >= SCHEMA
        and isinstance(version, int)
        and not isinstance(version, bool)
        and version >= MIGRATION_VERSION
    )


def read_generation(state_dir: Path) -> Optional[int]:
    doc, status = load_registry(state_dir)
    return doc["generation"] if status == STATUS_OK and doc is not None else None


def marker_generation(state_dir: Path) -> int:
    held = read_marker(state_dir)
    return held.generation if held else 0


def read_marker(state_dir: Path) -> Optional[registry_marker.Marker]:
    path = db_path_for(state_dir)
    if not path.exists():
        return None
    try:
        conn = connect(path, create=False)
        try:
            return registry_marker.read_marker(conn)
        finally:
            conn.close()
    except (DatastoreError, sqlite3.Error) as exc:
        logger.warning("plugin_registry_marker_unreadable", error_type=type(exc).__name__)
        return None


def _migrated_per_marker(state_dir: Path) -> bool:
    held = read_marker(state_dir)
    return held is not None and (held.schema >= SCHEMA or held.migration_version >= MIGRATION_VERSION)


def record_marker(
    state_dir: Path,
    generation: int,
    *,
    migration_version: Optional[int] = None,
    migrated_at: Optional[str] = None,
) -> None:
    path = db_path_for(state_dir)
    if not path.exists():
        logger.debug("plugin_registry_marker_skipped", reason="no_database")
        return
    conn = connect(path, create=False)
    try:
        conn.execute(f"PRAGMA busy_timeout={MARKER_BUSY_MS}")
        registry_marker.write_marker(conn, generation, SCHEMA, migration_version, migrated_at)
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        logger.debug("plugin_registry_marker_skipped", reason="no_table")
    finally:
        conn.close()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    temp = unique_tmp_path(path)
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def on_write(listener: Callable[[], None]) -> None:
    _write_listeners.append(listener)


def write_registry(path: Path, document: Dict[str, Any]) -> None:
    assert_test_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _write_bytes_atomic(path.with_suffix(path.suffix + ".bak"), path.read_bytes())
    temp = unique_tmp_path(path)
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, REGISTRY_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), REGISTRY_FILE_MODE)
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    _cache.pop(str(path), None)
    for listener in list(_write_listeners):
        listener()


def _process_lock(key: str) -> threading.RLock:
    with _proc_locks_guard:
        return _proc_locks.setdefault(key, threading.RLock())


def _take_flock(path: Path, timeout: float) -> int:
    assert_test_write_allowed(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise RegistryBusy(f"{path}: the plugin registry lock file cannot be made or opened ({type(exc).__name__})") from exc
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise RegistryBusy(f"{path}: another process holds the plugin registry lock") from None
            time.sleep(LOCK_POLL_SECONDS)


@contextmanager
def exclusive(
    state_dir: Path,
    *,
    timeout: Optional[float] = None,
    busy_error: Optional[Callable[[str], Exception]] = None,
) -> Iterator[_Frame]:
    timeout = LOCK_WAIT_SECONDS if timeout is None else timeout
    key = os.path.realpath(state_dir)
    lock = _process_lock(key)
    try:
        if not lock.acquire(timeout=timeout):
            raise RegistryBusy(f"{key}: another thread holds the plugin registry lock")
    except RegistryBusy as exc:
        if busy_error is None:
            raise
        raise busy_error(str(exc)) from exc
    frames: Dict[str, _Frame] = _held.__dict__.setdefault("frames", {})
    try:
        frame = frames.get(key)
        if frame is None:
            try:
                fd = _take_flock(lock_path(state_dir), timeout)
            except RegistryBusy as exc:
                if busy_error is None:
                    raise
                raise busy_error(str(exc)) from exc
            frame = frames[key] = _Frame(fd=fd)
        frame.depth += 1
        try:
            yield frame
        finally:
            frame.depth -= 1
            if frame.depth == 0:
                try:
                    del frames[key]
                finally:
                    os.close(frame.fd)
    finally:
        lock.release()


@contextmanager
def locked(state_dir: Path, thread_lock: Any, busy_error: Callable[[str], Exception]) -> Iterator[_Frame]:
    with exclusive(state_dir, busy_error=busy_error) as frame, thread_lock:
        yield frame


def read_for_mutation(state_dir: Path, *, log_event: str = "plugin_registry_unreadable") -> Dict[str, Any]:
    doc, status = load_registry(state_dir)
    if status == STATUS_UNREADABLE:
        logger.error(log_event, reason="registry_unreadable", path=str(registry_path(state_dir)))
        raise RegistryUnreadable(f"{registry_path(state_dir)}: registry is unreadable")
    if status == STATUS_MISSING or doc is None:
        if _migrated_per_marker(state_dir):
            logger.error(log_event, reason="registry_missing_after_flip", path=str(registry_path(state_dir)))
            raise RegistryUnreadable(f"{registry_path(state_dir)}: registry is missing after flip")
        return new_document(generation=0)
    out = copy.deepcopy(doc)
    out.setdefault("schema", SCHEMA)
    switches = out.setdefault("switches", {})
    switches.setdefault("third_party", False)
    sl = switches.setdefault("sideload", {})
    sl.setdefault("enabled_at", None)
    sl.setdefault("hours", DEFAULT_SIDELOAD_HOURS)
    sl.setdefault("expires_at", None)
    out.setdefault("items", {})
    out.setdefault("tombstones", {})
    out.setdefault("non_sidecar_sideloads", {})
    return out


def save_document(state_dir: Path, document: Dict[str, Any], *, log_event: str = "plugin_registry_write_failed") -> bool:
    reason = read_only_reason(state_dir)
    if reason is not None:
        logger.warning(log_event, reason="registry_read_only", detail=reason)
        return False
    path = registry_path(state_dir)
    assert_test_write_allowed(path)
    try:
        with exclusive(state_dir):
            cur_doc, cur_status = load_registry(state_dir)
            if cur_status == STATUS_UNREADABLE:
                logger.error(log_event, reason="registry_unreadable", path=str(path))
                return False
            cur_gen = cur_doc["generation"] if cur_doc is not None else 0
            doc_gen = document.get("generation") if isinstance(document.get("generation"), int) else 0
            generation = max(cur_gen, doc_gen, marker_generation(state_dir)) + 1
            to_write = copy.deepcopy(document)
            to_write["schema"] = SCHEMA
            to_write["generation"] = generation
            if MIGRATION_KEY not in to_write:
                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                to_write[MIGRATION_KEY] = {"version": MIGRATION_VERSION, MIGRATED_AT_KEY: stamp}
            write_registry(path, to_write)
    except RegistryBusy as exc:
        logger.warning(log_event, reason="registry_lock", error=str(exc)[:200])
        return False
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(log_event, reason="registry_write_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return False
    try:
        block = to_write.get(MIGRATION_KEY) if isinstance(to_write.get(MIGRATION_KEY), Mapping) else {}
        record_marker(
            state_dir,
            generation,
            migration_version=block.get("version", MIGRATION_VERSION),
            migrated_at=block.get(MIGRATED_AT_KEY),
        )
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__, generation=generation)
    return True


def commit(state_dir: Path, mutate: Callable[[Dict[str, Any]], T], *, log_event: str = "plugin_registry_write_failed") -> T:
    reason = read_only_reason(state_dir)
    if reason is not None:
        logger.warning(log_event, reason="registry_read_only", detail=reason)
        raise OSError(f"{registry_path(state_dir)}: registry is read-only ({reason})")
    with exclusive(state_dir):
        doc = read_for_mutation(state_dir, log_event=log_event)
        before = copy.deepcopy(doc)
        result = mutate(doc)
        if doc != before and not save_document(state_dir, doc, log_event=log_event):
            raise OSError(f"{registry_path(state_dir)}: write failed")
        return result


def describe(state_dir: Path) -> Tuple[Optional[int], str]:
    generation = read_generation(state_dir)
    if read_only_reason(state_dir) is not None:
        return generation, SOURCE_READ_ONLY
    doc, status = load_registry(state_dir)
    if status == STATUS_OK and is_migrated(doc):
        return generation, SOURCE_REGISTRY
    return generation, SOURCE_NONE
