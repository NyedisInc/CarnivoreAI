
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.db import DatastoreError, connect, db_path_for
from src.core.json_artifact import atomic_write_json
from src.core.plugin_registry import marker as registry_marker
from src.core.test_write_guard import assert_test_write_allowed
from src.core.unique_tmp_path import unique_tmp_path
from src.cplugs.host import registry_projection as projection

logger = structlog.get_logger()

STATE_DIR_NAME = "cplugs"
STATE_FILE = "state.json"
LEDGER_FILE = "installs.json"
SIDELOAD_FILE = "sideload.json"
THIRD_PARTY_FILE = "third-party.json"
REGISTRY_FILE = "plugins.json"
LOCK_FILE = ".plugins.lock"
BACKUP_PREFIX = "migration-backup-"

LEGACY_FILES: Dict[str, str] = {"state": STATE_FILE, "installs": LEDGER_FILE, "sideload": SIDELOAD_FILE, "third_party": THIRD_PARTY_FILE}
MARKER_BUSY_MS = 2000
"""How long the marker write waits on a busy ``carnivore.db`` while the registry lock is held."""
REGISTRY_FILE_MODE = 0o644
"""``plugins.json`` is written readable by the owner and others on the machine, as the plan says (5.2); the stores it stands for stay 0600."""
MIGRATION_KEY = "migration"
LEDGER_COPY_KEY = "ledger_copy"
MIGRATION_VERSION = 1
"""The version of the one migration (5.3). A ``plugins.json`` whose ``migration.version`` is at least this is the source of truth."""

STATUS_OK, STATUS_MISSING, STATUS_UNREADABLE = "ok", "missing", "unreadable"

_read_only: Dict[str, str] = {}
_guard = threading.Lock()
_cache: Dict[str, Tuple[int, int, int, Dict[str, Any], Optional[Dict[str, Dict[str, Any]]]]] = {}


def cplugs_dir(state_dir: Path) -> Path:
    return Path(state_dir) / STATE_DIR_NAME


def legacy_path(state_dir: Path, name: str) -> Path:
    return cplugs_dir(state_dir) / LEGACY_FILES[name]


def lock_path(state_dir: Path) -> Path:
    return Path(state_dir) / LOCK_FILE


def registry_path(state_dir: Path) -> Path:
    return cplugs_dir(state_dir) / REGISTRY_FILE


def backup_dir(state_dir: Path, generation: int) -> Path:
    return cplugs_dir(state_dir) / f"{BACKUP_PREFIX}{generation}"


def backups_newest_first(state_dir: Path) -> List[Path]:
    root = cplugs_dir(state_dir)
    if not root.is_dir():
        return []
    found = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX)]
    return sorted(found, key=lambda p: p.stat().st_mtime_ns, reverse=True)


def _key(state_dir: Path) -> str:
    return os.path.realpath(state_dir)


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
    return (isinstance(doc, dict) and isinstance(doc.get("generation"), int) and not isinstance(doc.get("generation"), bool)
            and isinstance(doc.get("items"), dict) and isinstance(doc.get("tombstones"), dict))


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
        logger.warning("plugin_registry_unreadable", path=path.name, error_type=type(exc).__name__)
        return None, STATUS_UNREADABLE
    signature = (info.st_ino, info.st_mtime_ns, info.st_size)
    held = _cache.get(key)
    if held is not None and held[:3] == signature:
        return held[3], STATUS_OK
    doc, status = parse_registry(path)
    if doc is None:
        _cache.pop(key, None)
        return None, status
    _cache[key] = (*signature, doc, None)
    return doc, STATUS_OK


def is_migrated(doc: Optional[Mapping[str, Any]]) -> bool:
    block = doc.get(MIGRATION_KEY) if isinstance(doc, Mapping) else None
    version = block.get("version") if isinstance(block, Mapping) else None
    return isinstance(version, int) and not isinstance(version, bool) and version >= MIGRATION_VERSION


def flipped_views(state_dir: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    if read_only_reason(state_dir) is not None:
        return None
    doc, status = load_registry(state_dir)
    if status != STATUS_OK or not is_migrated(doc):
        return None
    key = str(registry_path(state_dir))
    held = _cache.get(key)
    if held is not None and held[3] is doc:
        if held[4] is None:
            _cache[key] = (*held[:4], projection.join(doc))
        return _cache[key][4]
    return projection.join(doc)


def flipped_copy(state_dir: Path, name: str) -> Optional[Dict[str, Any]]:
    views = flipped_views(state_dir)
    return json.loads(json.dumps(views[name])) if views is not None else None


def read_generation(state_dir: Path) -> Optional[int]:
    doc, status = load_registry(state_dir)
    return doc["generation"] if status == STATUS_OK else None


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


def record_marker(state_dir: Path, generation: int, *, migration_version: Optional[int] = None, migrated_at: Optional[str] = None) -> None:
    path = db_path_for(state_dir)
    if not path.exists():
        logger.debug("plugin_registry_marker_skipped", reason="no_database")
        return
    conn = connect(path, create=False)
    try:
        conn.execute(f"PRAGMA busy_timeout={MARKER_BUSY_MS}")
        registry_marker.write_marker(conn, generation, projection.SCHEMA, migration_version, migrated_at)
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


def mirror(state_dir: Path, docs: Mapping[str, Mapping[str, Any]], generation: int) -> bool:
    ok = True
    for name in LEGACY_FILES:
        stamped = {**docs[name], projection.MIRROR_STAMP: generation}
        ok = atomic_write_json(legacy_path(state_dir, name), stamped, log_event="plugin_registry_mirror_failed") and ok
    return ok


def carried(doc: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: doc[k] for k in (MIGRATION_KEY, LEDGER_COPY_KEY) if k in doc}


def write_flipped(state_dir: Path, name: str, payload: Dict[str, Any], *, log_event: str) -> bool:
    assert_test_write_allowed(registry_path(state_dir))
    doc, status = load_registry(state_dir)
    if status != STATUS_OK or not is_migrated(doc):
        logger.error(log_event, reason="registry_not_usable", status=status)
        return False
    docs = projection.join(doc)
    docs[name] = projection.normalize({name: payload})[name]
    generation = max(doc["generation"], marker_generation(state_dir)) + 1
    try:
        write_registry(registry_path(state_dir), projection.build_document(generation=generation, docs=docs, carry=carried(doc)))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(log_event, reason="registry_write_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return False
    try:
        record_marker(state_dir, generation)
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__, generation=generation)
    if not mirror(state_dir, docs, generation):
        logger.error("plugin_registry_mirror_incomplete", generation=generation)
    return True
