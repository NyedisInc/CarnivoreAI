
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import structlog

from src.core.test_write_guard import assert_test_write_allowed
from src.core.work import tables
from src.core.work.importer import copy
from src.core.work.importer.errors import WorkImportDeferred
from src.core.work.ladder import SCHEMA_VERSION as LEGACY_VERSION
from src.core.work.work_ladder import MIGRATIONS, VERSION, VERSION_KEY
from src.cplugs.sdk import storage_backup
from src.cplugs.sdk.storage import CplugSchemaError, CplugStorage, StorageSpec

logger = structlog.get_logger(__name__)

LEGACY_DB = "huddle.db"
MARKER = "IMPORTED.json"
BACKUP_LABEL = "pre-work-import"
STORE_HOME = "carnivore.db"

_lock = threading.Lock()
Identity = Optional[Tuple[int, int]]
_ready: Dict[Path, Identity] = {}
_deferred: Dict[Path, Tuple[Identity, str]] = {}


def _identity(path: Path) -> Identity:
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino


def legacy_spec() -> StorageSpec:
    from src.core.work.ladder import BACKUPS, MIGRATIONS as LEGACY_MIGRATIONS  # noqa: PLC0415

    return StorageSpec(db=LEGACY_DB, migrations=LEGACY_MIGRATIONS, legacy_db=LEGACY_DB, backup_before=BACKUPS)


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _record(conn: sqlite3.Connection) -> Optional[tuple]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tables.IMPORTS,)).fetchone():
        return None
    return conn.execute(f"SELECT store_home, kind, source, source_version, source_sha256, counts, digests, imported_at "
                        f"FROM {tables.IMPORTS} WHERE id = 1").fetchone()


def _work_tables_present(conn: sqlite3.Connection) -> list:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'work\\_%' ESCAPE '\\'")]


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_switch(conn: sqlite3.Connection, kind: str, source: str = "", version: Optional[int] = None, sha: str = "",
                  result: Optional[copy.CopyResult] = None) -> None:
    conn.execute(f"INSERT INTO {tables.IMPORTS} (id, store_home, kind, source, source_version, source_sha256, counts, digests, imported_at) "
                 "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (STORE_HOME, kind, source, version, sha, json.dumps(result.counts if result else {}, sort_keys=True),
                  json.dumps(result.digests if result else {}, sort_keys=True), _now()))
    conn.execute(f"INSERT INTO {tables.META} (k, v) VALUES (?, ?)", (VERSION_KEY, 1))


def _walk(conn: sqlite3.Connection) -> None:
    row = conn.execute(f"SELECT v FROM {tables.META} WHERE k = ?", (VERSION_KEY,)).fetchone()
    version = int(row[0]) if row else 0
    if version > VERSION:
        raise WorkImportDeferred(f"the work store is at W{version}, newer than this build (W{VERSION})")
    for step in range(max(version, 1), VERSION):
        conn.execute("BEGIN IMMEDIATE")
        try:
            copy.run_script(conn, MIGRATIONS[step])
            conn.execute(f"UPDATE {tables.META} SET v = ? WHERE k = ?", (step + 1, VERSION_KEY))
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            raise WorkImportDeferred(f"work rung W{step + 1} failed: {exc}") from exc


def _mark_leftover(folder: Path, record: tuple) -> None:
    legacy, marker = folder / LEGACY_DB, folder / MARKER
    if not legacy.exists() or marker.exists():
        return
    body = {"store_home": record[0], "kind": record[1], "source": record[2], "source_version": record[3], "source_sha256": record[4],
            "counts": json.loads(record[5]), "imported_at": record[7],
            "note": "this huddle.db is a read-only leftover of the one-way import into carnivore.db (issue #1711, P2); keep it"}
    assert_test_write_allowed(marker)
    temp = marker.with_name(f".{MARKER}.partial")
    temp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    os.replace(temp, marker)
    mode = legacy.stat().st_mode
    os.chmod(legacy, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    logger.info("work_import_leftover_marked", leftover=str(legacy))


def _legacy_storage(folder: Path, state_dir: Optional[Path]) -> CplugStorage:
    return CplugStorage(folder, legacy_spec(), state_dir)


def _fresh(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN EXCLUSIVE")
    try:
        if _record(conn) is None:
            copy.create_empty(conn)
            _write_switch(conn, "fresh")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    logger.info("work_store_fresh")


def _import(conn: sqlite3.Connection, legacy: Path) -> copy.CopyResult:
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(f"ATTACH DATABASE ? AS {copy.LEGACY}", (str(legacy),))
    try:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            if _record(conn) is not None:
                conn.execute("ROLLBACK")
                return copy.CopyResult()
            version = int(conn.execute(f"PRAGMA {copy.LEGACY}.user_version").fetchone()[0])
            if version != LEGACY_VERSION:
                raise WorkImportDeferred(f"huddle.db is at rung {version}, not {LEGACY_VERSION}")
            sha = sha256_of(legacy)
            result = copy.copy_legacy(conn)
            _write_switch(conn, "import", str(legacy), version, sha, result)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute(f"DETACH DATABASE {copy.LEGACY}")
        conn.execute("PRAGMA foreign_keys=ON")
    if sha256_of(legacy) != sha:
        logger.error("work_import_source_changed", leftover=str(legacy))
    return result


def _prepare(db_path: Path, folder: Path, state_dir: Optional[Path]) -> None:
    assert_test_write_allowed(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(open_db(db_path)) as conn:
        record = _record(conn)
        if record is None and _work_tables_present(conn):
            raise WorkImportDeferred(f"carnivore.db holds work tables but no import record: {sorted(_work_tables_present(conn))[:5]}")
        if record is None:
            legacy_storage = _legacy_storage(folder, state_dir)
            legacy = legacy_storage.db_path
            if not legacy.exists():
                if any(Path(f"{legacy}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm")):
                    raise WorkImportDeferred(f"{legacy.name} is missing but its side files are not")
                _fresh(conn)
            else:
                try:
                    legacy_storage.connect(True).close()
                    with closing(sqlite3.connect(str(legacy), timeout=30.0)) as source:
                        backup = storage_backup.take(source, legacy, BACKUP_LABEL, expect_version=LEGACY_VERSION)
                except (CplugSchemaError, storage_backup.BackupFailed, sqlite3.Error, OSError) as exc:
                    raise WorkImportDeferred(f"huddle.db could not be prepared: {exc}") from exc
                try:
                    result = _import(conn, legacy)
                except sqlite3.Error as exc:
                    raise WorkImportDeferred(f"the import failed and rolled back: {exc}") from exc
                logger.info("work_import_done", source=str(legacy), backup=backup.name, counts=result.counts)
            record = _record(conn)
        _walk(conn)
    if record is not None and record[1] == "import":
        try:
            _mark_leftover(folder, record)
        except OSError as exc:
            logger.warning("work_import_marker_failed", error=str(exc))


def ensure(db_path: Path, folder: Path, state_dir: Optional[Path]) -> None:
    key = Path(db_path)
    with _lock:
        identity = _identity(key)
        if identity is not None and _ready.get(key) == identity:
            return
        held = _deferred.get(key)
        if held is not None and held[0] == identity:
            raise WorkImportDeferred(held[1])
        _ready.pop(key, None)
        try:
            _prepare(key, Path(folder), state_dir)
        except WorkImportDeferred as exc:
            _deferred[key] = (_identity(key), str(exc))
            logger.error("work_import_deferred", db=str(key), reason=str(exc))
            raise
        except (sqlite3.Error, OSError) as exc:
            reason = f"the work store could not be opened: {exc}"
            _deferred[key] = (_identity(key), reason)
            logger.error("work_import_deferred", db=str(key), reason=reason)
            raise WorkImportDeferred(reason) from exc
        _deferred.pop(key, None)
        _ready[key] = _identity(key)


def hold(db_path: Path, reason: str) -> None:
    with _lock:
        _deferred.setdefault(Path(db_path), (_identity(Path(db_path)), reason))
    logger.error("work_import_deferred", db=str(db_path), reason=reason)


def forget(db_path: Path) -> None:
    with _lock:
        _ready.pop(Path(db_path), None)
        _deferred.pop(Path(db_path), None)
