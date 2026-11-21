
from __future__ import annotations

import copy
import fcntl
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple, TypeVar

import structlog

from src.core.db import DatastoreError
from src.core.json_artifact import UnreadableArtifact, atomic_write_json, read_for_update
from src.core.test_write_guard import assert_test_write_allowed
from src.plugins.host import registry_files, registry_projection
from src.plugins.host.registry_files import (  # noqa: F401
    LEDGER_FILE, LEGACY_FILES, LOCK_FILE, REGISTRY_FILE, SIDELOAD_FILE, STATE_DIR_NAME, STATE_FILE, THIRD_PARTY_FILE,
    cplugs_dir, legacy_path, lock_path, read_generation, registry_path)

logger = structlog.get_logger()

LOCK_WAIT_SECONDS = 15.0
"""How long a writer waits for the lock before it is refused with :class:`RegistryBusy`."""
LOCK_POLL_SECONDS = 0.02

SOURCE_LEGACY = "legacy_files"
SOURCE_REGISTRY = "plugins.json"
SOURCE_NONE = "none"
SOURCE_READ_ONLY = "read_only"

T = TypeVar("T")


class RegistryBusy(OSError):
    pass


@dataclass
class _Frame:

    fd: int
    depth: int = 0
    dirty: bool = False


_proc_locks: Dict[str, threading.RLock] = {}
_proc_locks_guard = threading.Lock()
_held = threading.local()


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
def exclusive(state_dir: Path, *, timeout: Optional[float] = None,
              busy_error: Optional[Callable[[str], Exception]] = None) -> Iterator[_Frame]:
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
                    if frame.dirty:
                        project(state_dir)
                finally:
                    del frames[key]
                    os.close(frame.fd)
    finally:
        lock.release()


@contextmanager
def locked(state_dir: Path, thread_lock: Any, busy_error: Callable[[str], Exception]) -> Iterator[_Frame]:
    with exclusive(state_dir, busy_error=busy_error) as frame, thread_lock:
        yield frame


def write_document(state_dir: Path, name: str, payload: Dict[str, Any], *, log_event: str) -> bool:
    reason = registry_files.read_only_reason(state_dir)
    if reason is not None:
        logger.warning(log_event, reason="registry_read_only", detail=reason)
        return False
    try:
        with exclusive(state_dir) as frame:
            return _write_inside(state_dir, frame, name, payload, log_event)
    except RegistryBusy as exc:
        logger.warning(log_event, reason="registry_lock", error=str(exc)[:200])
        return False


def _write_inside(state_dir: Path, frame: _Frame, name: str, payload: Dict[str, Any], log_event: str) -> bool:
    doc, status = registry_files.load_registry(state_dir)
    if status == registry_files.STATUS_UNREADABLE:
        logger.error(log_event, reason="registry_unreadable")
        return False
    if registry_files.is_migrated(doc):
        return registry_files.write_flipped(state_dir, name, payload, log_event=log_event)
    if status == registry_files.STATUS_MISSING and _migrated_per_marker(state_dir):
        logger.error(log_event, reason="registry_missing_after_flip")
        return False
    written = atomic_write_json(legacy_path(state_dir, name), payload, log_event=log_event)
    frame.dirty = frame.dirty or written
    return written


def _migrated_per_marker(state_dir: Path) -> bool:
    held = registry_files.read_marker(state_dir)
    return held is not None and held.migration_version >= registry_files.MIGRATION_VERSION


class Documents:

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._loaded: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}

    def load(self, name: str) -> Dict[str, Any]:
        if name not in self._loaded:
            raw = read_store(self._state_dir, name, log_event="plugin_registry_store_unreadable")
            self._loaded[name] = (raw, copy.deepcopy(raw))
        return self._loaded[name][1]

    def changed(self) -> Dict[str, Dict[str, Any]]:
        return {n: edited for n, (original, edited) in self._loaded.items() if edited != original}


def read_store(state_dir: Path, name: str, *, log_event: str) -> Dict[str, Any]:
    copy_ = registry_files.flipped_copy(state_dir, name)
    return copy_ if copy_ is not None else read_for_update(legacy_path(state_dir, name), log_event=log_event)


def commit(state_dir: Path, mutate: Callable[[Documents], T], *, log_event: str = "plugin_registry_write_failed") -> T:
    with exclusive(state_dir):
        docs = Documents(state_dir)
        result = mutate(docs)
        for name, document in docs.changed().items():
            if not write_document(state_dir, name, document, log_event=log_event):
                raise OSError(f"{legacy_path(state_dir, name)}: write failed")
        return result


def _read_projection_inputs(state_dir: Path) -> Optional[Dict[str, Any]]:
    found: Dict[str, Any] = {}
    for name in LEGACY_FILES:
        try:
            found[name] = read_for_update(legacy_path(state_dir, name), log_event="plugin_registry_projection_input_unreadable")
        except UnreadableArtifact:
            return None
    return found


def project(state_dir: Path) -> Optional[int]:
    if registry_files.read_only_reason(state_dir) is not None:
        return None
    flipped, _ = registry_files.load_registry(state_dir)
    if registry_files.is_migrated(flipped):
        return None
    try:
        inputs = _read_projection_inputs(state_dir)
        if inputs is None:
            logger.warning("plugin_registry_projection_skipped", reason="a store is unreadable")
            return None
        generation = max(registry_files.read_generation(state_dir) or 0, registry_files.marker_generation(state_dir)) + 1
        registry_files.write_registry(registry_path(state_dir), registry_projection.build_document(generation=generation, docs=inputs))
    except (OSError, ValueError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_projection_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return None
    try:
        registry_files.record_marker(state_dir, generation)
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__, generation=generation)
    return generation


def describe(state_dir: Path) -> Tuple[Optional[int], str]:
    generation = read_generation(state_dir)
    if registry_files.read_only_reason(state_dir) is not None:
        return generation, SOURCE_READ_ONLY
    doc, _ = registry_files.load_registry(state_dir)
    if registry_files.is_migrated(doc):
        return generation, SOURCE_REGISTRY
    any_store = any(legacy_path(state_dir, name).exists() for name in LEGACY_FILES)
    return generation, SOURCE_LEGACY if any_store else SOURCE_NONE
