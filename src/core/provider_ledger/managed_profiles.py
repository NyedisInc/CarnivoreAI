
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from src.config.provider_accounts import MANAGED_ROOT, managed_dir_for

logger = structlog.get_logger()

__all__ = [
    "DIRECTORY_ABSENT",
    "DIRECTORY_KEPT",
    "DIRECTORY_REFUSED",
    "DIRECTORY_REMOVED",
    "MANAGED_ROOT",
    "MANAGED_DIR_MODE",
    "ManagedProfileError",
    "RemoveOutcome",
    "ensure_managed_dir",
    "is_managed_path",
    "managed_dir_for",
    "remove_managed_dir",
]

MANAGED_DIR_MODE = 0o700


class ManagedProfileError(Exception):
    pass


def _refuse_a_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ManagedProfileError(
            f"the profile directory {path} could not be created "
            "(it is a symbolic link, and a managed profile has to be a "
            "real directory under the managed root)"
        )


def _hold_at_mode(path: Path) -> None:
    current = stat.S_IMODE(path.stat().st_mode)
    if current & 0o077:
        path.chmod(MANAGED_DIR_MODE)


def ensure_managed_dir(account_id: str) -> str:
    path = Path(managed_dir_for(account_id))
    _refuse_a_symlink(path.parent.parent)
    _refuse_a_symlink(path.parent)
    _refuse_a_symlink(path)
    try:
        path.mkdir(mode=MANAGED_DIR_MODE, parents=True, exist_ok=True)
        _hold_at_mode(path)
        _hold_at_mode(path.parent)
        _hold_at_mode(path.parent.parent)
    except OSError as exc:
        logger.warning(
            "managed_profile_dir_unavailable",
            account_id=account_id,
            path=str(path),
            error=type(exc).__name__,
        )
        raise ManagedProfileError(
            f"the profile directory {path} could not be created "
            f"({type(exc).__name__})"
        ) from exc
    if not is_managed_path(str(path)):
        logger.warning(
            "managed_profile_dir_outside_root",
            account_id=account_id,
            path=str(path),
        )
        raise ManagedProfileError(
            f"the profile directory {path} did not land under "
            f"{MANAGED_ROOT}"
        )
    return str(path)


def is_managed_path(path: str) -> bool:
    root = os.path.realpath(os.path.expanduser(MANAGED_ROOT))
    candidate = os.path.realpath(os.path.expanduser(path))
    return candidate == root or candidate.startswith(root + os.sep)


DIRECTORY_REMOVED = "removed"
DIRECTORY_ABSENT = "absent"
DIRECTORY_REFUSED = "refused"

DIRECTORY_KEPT = "kept"

REFUSED_SYMLINK = "a level of the path is a symbolic link"
REFUSED_OUTSIDE_ROOT = "the path does not sit under the managed root"
REFUSED_NOT_A_DIRECTORY = "the path is not a directory"
REFUSED_REMOVE_FAILED = "the directory could not be removed"


@dataclass(frozen=True)
class RemoveOutcome:

    status: str
    path: str
    reason: Optional[str] = None


def _refused(path: Path, account_id: str, reason: str) -> RemoveOutcome:
    logger.warning(
        "managed_profile_remove_refused",
        account_id=account_id,
        path=str(path),
        reason=reason,
    )
    return RemoveOutcome(status=DIRECTORY_REFUSED, path=str(path), reason=reason)


def remove_managed_dir(account_id: str) -> RemoveOutcome:
    path = Path(managed_dir_for(account_id))
    for level in (path.parent.parent, path.parent, path):
        if level.is_symlink():
            return _refused(path, account_id, REFUSED_SYMLINK)
    root = os.path.realpath(os.path.expanduser(MANAGED_ROOT))
    if not is_managed_path(str(path)) or os.path.realpath(path) == root:
        return _refused(path, account_id, REFUSED_OUTSIDE_ROOT)
    if not path.exists():
        return RemoveOutcome(status=DIRECTORY_ABSENT, path=str(path))
    if not path.is_dir():
        return _refused(path, account_id, REFUSED_NOT_A_DIRECTORY)

    failures: list = []

    def collect(function, target, exc) -> None:
        failures.append(type(exc).__name__)

    shutil.rmtree(path, onexc=collect)
    if failures:
        return _refused(path, account_id, REFUSED_REMOVE_FAILED)
    logger.info("managed_profile_removed", account_id=account_id, path=str(path))
    return RemoveOutcome(status=DIRECTORY_REMOVED, path=str(path))
