
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import structlog

from src.core import product_identity

logger = structlog.get_logger()

_FALLBACK: Dict[str, Path] = {}

OUTCOME_NOTHING = "nothing_to_do"
OUTCOME_RENAMED = "renamed"
OUTCOME_EMPTY_REMOVED = "empty_legacy_removed"
OUTCOME_DEFERRED = "deferred"
OUTCOME_CONFLICT = "conflict"

_SIDECARS = ("-wal", "-shm", "-journal")


@dataclass(frozen=True)
class LegacyDbOutcome:

    outcome: str
    detail: str = ""


def legacy_fallback_for(state_dir: Path) -> Optional[Path]:
    return _FALLBACK.get(str(Path(state_dir)))


def _remove_sidecars(base: Path) -> None:
    for suffix in _SIDECARS:
        Path(f"{base}{suffix}").unlink(missing_ok=True)


def _is_empty_db(path: Path) -> bool:
    wal = Path(f"{path}-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    if path.stat().st_size == 0:
        return wal_bytes == 0
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)) as conn:
            return conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    except sqlite3.Error as exc:
        logger.warning("legacy_db_probe_failed", path=path.name, error=str(exc))
        return False


def _open_locked(path: Path) -> "sqlite3.Connection | str":
    try:
        conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=2, isolation_level=None)
    except sqlite3.Error as exc:
        return f"database could not be opened ({exc})"
    try:
        conn.execute("PRAGMA locking_mode=EXCLUSIVE")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error as exc:
        conn.close()
        return f"database is in use or unreadable ({exc})"


def _truncate_wal(conn: sqlite3.Connection) -> Optional[str]:
    try:
        busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    except sqlite3.Error as exc:
        return f"wal checkpoint failed ({exc})"
    return None if busy == 0 else "wal checkpoint reported busy"


def _backup_first(legacy: Path, state_dir: Path) -> Optional[str]:
    from src.core.db import SCHEMA_VERSION_PARSED, connect, read_schema_version
    from src.core.db_backup import take_backup

    try:
        with closing(connect(legacy, create=False)) as conn:
            read = read_schema_version(conn)
    except sqlite3.Error as exc:
        return f"schema version unreadable ({exc})"
    if read.outcome != SCHEMA_VERSION_PARSED or read.value is None:
        return "schema version unreadable"
    result = take_backup(legacy, state_dir, read.value)
    return None if result.verified else (result.reason or "backup not verified")


def migrate_legacy_db(state_dir: Path) -> LegacyDbOutcome:
    from src.core.db import DatastoreError

    state_dir = Path(state_dir)
    key = str(state_dir)
    _FALLBACK.pop(key, None)
    current = state_dir / product_identity.DB_FILENAME
    legacy = state_dir / product_identity.LEGACY_DB_FILENAMES[0]
    try:
        return _ladder(state_dir, key, current, legacy)
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        return _defer(key, current, legacy, f"{type(exc).__name__}: {exc}")


def _defer(key: str, current: Path, legacy: Path, reason: str) -> LegacyDbOutcome:
    logger.error("legacy_db_rename_deferred", reason=reason, state_dir=key)
    try:
        current_unusable = not current.exists() or _is_empty_db(current)
    except OSError:
        current_unusable = False
    if legacy.exists() and current_unusable:
        _FALLBACK[key] = legacy
    return LegacyDbOutcome(OUTCOME_DEFERRED, reason)


def _ladder(state_dir: Path, key: str, current: Path, legacy: Path) -> LegacyDbOutcome:
    if not legacy.exists():
        if not current.exists():
            return LegacyDbOutcome(OUTCOME_NOTHING, "no database yet")
        _remove_sidecars(legacy)
        return LegacyDbOutcome(OUTCOME_NOTHING, "already carnivore.db")

    if _is_empty_db(legacy):
        _remove_sidecars(legacy)
        legacy.unlink()
        logger.info("legacy_db_empty_removed", path=legacy.name)
        return LegacyDbOutcome(OUTCOME_EMPTY_REMOVED, "empty cloude.db deleted")

    if current.exists() and not _is_empty_db(current):
        logger.error(
            "legacy_db_conflict",
            state_dir=key,
            message="cloude.db and carnivore.db both hold data; neither was touched and carnivore.db stays in "
            "use. A human must decide which one to keep.",
        )
        return LegacyDbOutcome(OUTCOME_CONFLICT, "both databases hold tables")

    probe = _open_locked(legacy)
    if isinstance(probe, str):
        return _defer(key, current, legacy, probe)
    probe.close()
    reason = _backup_first(legacy, state_dir)
    if reason is not None:
        return _defer(key, current, legacy, reason)

    held = _open_locked(legacy)
    if isinstance(held, str):
        return _defer(key, current, legacy, held)
    try:
        reason = _truncate_wal(held)
        if reason is not None:
            return _defer(key, current, legacy, reason)
        if current.exists():
            if not _is_empty_db(current):
                return _defer(key, current, legacy, "carnivore.db appeared with data during the rename")
            _remove_sidecars(current)
            current.unlink()
        else:
            _remove_sidecars(current)
        os.replace(legacy, current)
    finally:
        held.close()
    _remove_sidecars(legacy)
    logger.info("legacy_db_renamed", frm=legacy.name, to=current.name)
    return LegacyDbOutcome(OUTCOME_RENAMED, "cloude.db renamed to carnivore.db")


def readable_db_path(state_dir: Path) -> Path:
    state_dir = Path(state_dir)
    current = state_dir / product_identity.DB_FILENAME
    legacy = state_dir / product_identity.LEGACY_DB_FILENAMES[0]
    if current.exists() and current.stat().st_size > 0:
        return current
    if legacy.exists() and legacy.stat().st_size > 0:
        return legacy
    return current


def script_default_db() -> str:
    path = readable_db_path(Path("~/Library/Application Support/Carnivore").expanduser())
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"no database found at {path} (and no cloude.db beside it); pass --db explicitly")
    return str(path)
