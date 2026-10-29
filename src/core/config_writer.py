
from __future__ import annotations

import json
import os
import stat
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger()

COMMITTED = "committed"
"""The new document is on disk and the backup holds the previous bytes."""

UNCHANGED = "unchanged"
"""The mutator reported nothing to do. NEITHER config.json NOR the
backup was touched, which is the behaviour ``migrate_config_file`` has
always had for an already-current config and which callers rely on."""

STALE_REVISION = "stale_revision"
"""A precondition evaluated against the FRESH in-lock read refused the
write. Nothing was written. The caller gets the current document back so
it can tell the client what it is racing against."""

BACKUP_UNAVAILABLE = "backup_unavailable"
"""``backup_required=True`` and the pre-write bytes could not be saved,
so the write was abandoned rather than performed without a rollback
path. Only the config migration asks for this posture."""

PRIVATE_FILE_MODE = 0o600
"""Mode of config.json, its ``.bak`` and the temp file between them when a
caller names no mode (#1834). config.json can carry credentials-adjacent
state, so it is owner-only from the first byte: the mode is set on the
temp file (``fchmod``) BEFORE ``os.replace``, never by a chmod afterwards,
so there is no window in which the new file is readable by others."""

_locks: Dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()

_depth = threading.local()

_listeners: list = []


@dataclass(frozen=True)
class CommitOutcome:

    status: str
    data: Dict[str, Any]
    wrote: bool


def _lock_for(path: Path) -> threading.RLock:
    key = os.path.realpath(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def read_config(config_path: Path) -> Dict[str, Any]:
    resolved = Path(config_path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"Auth config file not found: {resolved}")
    try:
        with open(resolved) as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {resolved}: {exc}")


def commit(
    config_path: Path,
    mutate: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    *,
    backup_required: bool = False,
    precondition: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    file_mode: Optional[int] = None,
    external_writer: bool = False,
    backup: bool = True,
) -> CommitOutcome:
    resolved = Path(config_path).expanduser()
    if file_mode is None:
        file_mode = PRIVATE_FILE_MODE

    if getattr(_depth, "value", 0):
        raise RuntimeError(
            "config_writer.commit() was called from inside a mutator. The "
            "mutator is already holding the freshly-read document; a nested "
            "commit would re-read the pre-mutation state and lose the outer "
            "write."
        )

    with _lock_for(resolved):
        _depth.value = getattr(_depth, "value", 0) + 1
        try:
            if not resolved.exists():
                raise FileNotFoundError(
                    f"Auth config file not found: {resolved}\n"
                    f"Run ./setup_auth.py to create it."
                )
            seen = _file_identity(resolved) if external_writer else None
            with open(resolved) as handle:
                raw = handle.read()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in auth config file: {exc}\nCheck {resolved}")

            if precondition is not None:
                refusal = precondition(data)
                if refusal is not None:
                    return CommitOutcome(status=refusal, data=data, wrote=False)

            new_data = mutate(data)
            if new_data is None:
                return CommitOutcome(status=UNCHANGED, data=data, wrote=False)

            if backup:
                backup_path = resolved.with_suffix(resolved.suffix + ".bak")
                try:
                    _write_backup(backup_path, raw, file_mode)
                except OSError as exc:
                    logger.warning(
                        "config_write_backup_failed",
                        path=str(resolved),
                        error=str(exc),
                        required=backup_required,
                    )
                    if backup_required:
                        return CommitOutcome(
                            status=BACKUP_UNAVAILABLE, data=data, wrote=False
                        )

            still_current = (
                (lambda: _file_identity(resolved) == seen) if external_writer else None
            )
            if not _replace_atomically(
                resolved, new_data, mode=file_mode, still_current=still_current
            ):
                return CommitOutcome(status=STALE_REVISION, data=data, wrote=False)
            if not external_writer:
                _notify(resolved, new_data)
            return CommitOutcome(status=COMMITTED, data=new_data, wrote=True)
        finally:
            _depth.value -= 1


def create_if_absent(
    path: Path, data: Dict[str, Any], *, file_mode: Optional[int] = None
) -> bool:
    resolved = Path(path).expanduser()
    with _lock_for(resolved):
        if resolved.exists():
            return False
        tmp_path = resolved.with_suffix(
            f"{resolved.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            with _open_with_mode(tmp_path, file_mode or 0o644, exclusive=True) as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(tmp_path, resolved)
        except FileExistsError:
            return False
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        return True


def _file_identity(path: Path) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _open_with_mode(path: Path, mode: Optional[int], *, exclusive: bool):
    if mode is None:
        return open(path, "w")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, mode)
    try:
        os.fchmod(fd, mode)
    except OSError:
        os.close(fd)
        raise
    return os.fdopen(fd, "w")


def _write_backup(path: Path, text: str, mode: Optional[int]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with _open_with_mode(tmp_path, mode, exclusive=True) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _replace_atomically(
    path: Path,
    data: Dict[str, Any],
    *,
    mode: Optional[int] = None,
    still_current: Optional[Callable[[], bool]] = None,
) -> bool:
    tmp_path = path.with_suffix(
        f"{path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        with _open_with_mode(tmp_path, mode, exclusive=True) as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        if still_current is not None and not still_current():
            tmp_path.unlink()
            return False
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def on_commit(listener: Callable[[Path, Dict[str, Any]], None]) -> None:
    _listeners.append(listener)


def _notify(path: Path, data: Dict[str, Any]) -> None:
    for listener in list(_listeners):
        try:
            listener(path, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "config_commit_listener_failed",
                listener=getattr(listener, "__qualname__", repr(listener)),
                error=str(exc),
            )


def tighten_existing(config_path: Path) -> list:
    resolved = Path(config_path).expanduser()
    changed: list = []
    for candidate in [resolved, *sorted(resolved.parent.glob(resolved.name + ".bak*"))]:
        try:
            fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("config_tighten_skipped", path=str(candidate), error=str(exc))
            continue
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 == 0:
                continue
            os.fchmod(fd, st.st_mode & 0o700)
            changed.append(str(candidate))
            logger.info(
                "config_file_tightened",
                path=str(candidate),
                old_mode=oct(stat.S_IMODE(st.st_mode)),
            )
        except OSError as exc:
            logger.warning("config_tighten_failed", path=str(candidate), error=str(exc))
        finally:
            os.close(fd)
    return changed
