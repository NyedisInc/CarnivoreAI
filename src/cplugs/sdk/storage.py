
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.db_reuse.lent import LentConnection
from src.core.db_reuse.pooled_read import ReadPool
from src.core.test_write_guard import assert_test_write_allowed
from src.cplugs.sdk import storage_backup, storage_reconcile

logger = structlog.get_logger()

_move_lock = threading.Lock()
_walk_lock = threading.Lock()
_walk_failed: Dict[Path, Tuple[Tuple[int, int], str]] = {}
_SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


class CplugSchemaError(Exception):
    pass


class PostBackupFailure(CplugSchemaError):
    pass


def _signature(path: Path) -> Tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


@dataclass(frozen=True)
class StorageSpec:
    """What a plugin declares about its storage.

    Inputs: db (str) - the file name inside the plugin folder; migrations (SQL scripts, the ladder);
      legacy_db (str | None) - a file directly under the state directory moved in once (``huddle.db``);
      backup_before ({rung number: label} | None) - a verified copy of the file (``storage_backup.py``) is taken, labelled,
      before a file behind that rung walks to or past it; None takes none. Must be immutable (``MappingProxyType``).
    """

    db: str
    migrations: Sequence[str]
    legacy_db: Optional[str] = None
    backup_before: Optional[Mapping[int, str]] = None


@dataclass(frozen=True)
class CoreStorageSpec:

    bind: Callable[[Path, Optional[Path]], "CplugStorage"]


_SharedReadConnection = LentConnection


class CplugStorage:

    def __init__(self, folder: Path, spec: Optional[StorageSpec], state_dir: Optional[Path] = None) -> None:
        self.path = Path(folder)
        self._spec = spec
        self._state_dir = Path(state_dir) if state_dir is not None else None
        self._scope = threading.local()
        self._reads = ReadPool(lambda _path: self._open(False))

    @contextmanager
    def read_scope(self) -> Iterator[None]:
        state = self._scope.__dict__
        state["depth"] = state.get("depth", 0) + 1
        try:
            yield
        finally:
            state["depth"] -= 1
            if state["depth"] == 0:
                for conn in state.pop("retired", []):
                    conn.close()
                if state.get("conn") is not None:
                    conn, state["conn"] = state["conn"], None
                    conn.close()

    @property
    def db_path(self) -> Path:
        if self._spec is None:
            raise CplugSchemaError("this plugin declares no storage")
        target = self.path / self._spec.db
        self._move_legacy(target)
        return target

    @property
    def schema_version(self) -> int:
        return len(self._spec.migrations) if self._spec else 0

    def _move_legacy(self, target: Path) -> None:
        if self._spec is None or not self._spec.legacy_db or self._state_dir is None:
            return
        old = self._state_dir / self._spec.legacy_db
        if target.exists() or not old.exists():
            return
        with _move_lock:
            if target.exists() or not old.exists():
                return
            assert_test_write_allowed(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.moving")
            for suffix in ("",) + _SIDE_SUFFIXES:
                stale = Path(f"{temp}{suffix}")
                if stale.exists():
                    stale.unlink()  # left by a crash
            source = sqlite3.connect(str(old), timeout=5.0)
            try:
                dest = sqlite3.connect(str(temp))
                try:
                    source.backup(dest)
                    dest.execute("PRAGMA journal_mode=DELETE")
                finally:
                    dest.close()
            finally:
                source.close()
            with open(temp, "rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, target)
            logger.info("cplug_storage_moved", source=str(old), target=str(target), source_kept=True)

    def connect(self, write: bool) -> sqlite3.Connection:
        state = self._scope.__dict__
        if not write and state.get("depth", 0) > 0:
            if state.get("conn") is not None and state.get("placeholder") and self.db_path.exists():
                state.setdefault("retired", []).append(state["conn"])
                state["conn"] = None
            if state.get("conn") is None:
                state["placeholder"] = not self.db_path.exists()
                state["conn"] = self._open(False)
            return _SharedReadConnection(state["conn"])  # type: ignore[return-value]
        return self._open(write)

    def connect_read(self) -> sqlite3.Connection:
        """A read connection reused across calls on this thread (a no-op ``close``); the hot readers use it instead of ``connect(False)``.

        Description: inside a ``read_scope`` it is the scope's connection. A file that does not exist yet answers a fresh stand-in
          (nothing to reuse, nothing created). Otherwise one connection per thread and file stays open, at the latest schema, with no
          transaction held between calls, so a write through any connection is visible to the next read. A replaced file is re-opened.
        Output: a connection to use in ``with closing(...)`` like ``connect(False)``. Raises: as ``connect``.
        """
        if self._scope.__dict__.get("depth", 0) > 0 or not self.db_path.exists():
            return self.connect(False)
        return self._reads.lend(self.db_path)  # type: ignore[return-value]

    def _open(self, write: bool) -> sqlite3.Connection:
        path = self.db_path
        if not write and not path.exists():
            conn = sqlite3.connect(":memory:")
        else:
            assert_test_write_allowed(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with _walk_lock:
                known = _walk_failed.get(path)
                if known is not None and known[0] == _signature(path):
                    raise CplugSchemaError(known[1])
                try:
                    migrate(conn, self._spec.migrations if self._spec else (), name=path.name, path=path,
                            backup_before=self._spec.backup_before if self._spec else None)
                except PostBackupFailure as exc:
                    _walk_failed[path] = (_signature(path), str(exc))
                    raise
        except (CplugSchemaError, sqlite3.Error):
            conn.close()
            raise
        return conn

    def size_bytes(self) -> int:
        if not self.path.exists():
            return 0
        return sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())


def migrate(conn: sqlite3.Connection, migrations: Sequence[str], *, name: str, path: Optional[Path] = None,
            backup_before: Optional[Mapping[int, str]] = None) -> None:
    latest = len(migrations)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > latest:
        raise CplugSchemaError(f"{name} is schema {version}; this build knows {latest}")
    took = False
    for rung, label in sorted((backup_before or {}).items()):
        if 0 < version < rung <= latest and path is not None:
            try:
                storage_backup.take(conn, path, label, expect_version=version)
                took = True
            except (storage_backup.BackupFailed, sqlite3.Error, OSError) as exc:
                logger.error("cplug_schema_backup_failed", db=name, rung=rung, error=str(exc)[:300])
                raise CplugSchemaError(f"{name} is schema {version}; the backup before rung {rung} failed: {exc}") from exc
            break
    failure = PostBackupFailure if took else CplugSchemaError
    try:
        if 0 < version < latest:
            try:
                decided = storage_reconcile.plan(conn, migrations, version)
                if decided.diverged:
                    storage_reconcile.apply(conn, migrations, decided, name=name)
                    return
            except storage_reconcile.ReconcileRefused as exc:
                raise failure(f"{name} is schema {version} but its objects do not match this ladder: {exc}") from exc
        for step in range(version, latest):
            with conn:
                conn.executescript(f"BEGIN; {migrations[step]} PRAGMA user_version = {step + 1}; COMMIT;")
            logger.info("cplug_schema_migrated", db=name, to=step + 1)
    except sqlite3.Error as exc:
        if not took:
            raise
        logger.error("cplug_schema_walk_failed_after_backup", db=name, error=str(exc)[:300])
        raise PostBackupFailure(f"{name} is schema {version}; a step failed after its backup: {exc}") from exc
