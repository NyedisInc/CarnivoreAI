"""Creating the directory a managed account's login lives in, and nothing else.

**THE REMOVAL RE-DERIVES ITS TARGET; IT NEVER DELETES A STORED STRING.**
The only input is the validated slug, the path comes from
:func:`managed_dir_for`, and the same symlink ladder the creation runs is
run again before anything is removed. A stored pointer, which a
hand-edited ``config.json`` can spell anything at all, is never the thing
handed to ``rmtree``.

**AND NO LEVEL OF IT MAY BE A SYMLINK.** ``mkdir`` follows one and
``chmod`` narrows what it points AT, so a ``~/.carnivore`` that is a link
into a directory somebody else owns would have this app create a
credential store outside the root it thinks it owns and set that other
directory to 0700 on the way past. Measured: with ``~/.carnivore`` linked
to a 0755 scratch directory, the scratch directory came back 0700 with
``accounts/claude1`` inside it. So every level is checked BEFORE anything
is created, the refusal is the ordinary :class:`ManagedProfileError` the
route already answers 409 for, and :func:`is_managed_path` is then the
after-the-fact assertion that the leaf really did land under the root.

**THE MODE IS VERIFIED, NOT ASSUMED.** ``Path.mkdir(mode=...)`` is
masked by the process umask, and ``parents=True`` creates the
intermediate directories with the default mode and ignores ``mode``
entirely. So every level is chmod'ed after the fact when it is wider
than 0700. A permissive umask must not be able to leave a credential
store world readable.

**THE PATH ITSELF IS DERIVED IN THE CONFIG PACKAGE**
(:func:`src.config.provider_accounts.managed_dir_for`), not here, and it
is re-exported below so a caller needs one import. The derivation has to
live there because :func:`~src.config.provider_accounts.profile_dir_for`
answers the same string for the reader, the login and the keychain
lookup, and ``src/config`` may not import ``src/core``.
"""

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
    """A managed profile directory could not be created or secured.
    """


def _refuse_a_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ManagedProfileError(
            f"the profile directory {path} could not be created "
            "(it is a symbolic link, and a managed profile has to be a "
            "real directory under the managed root)"
        )


def _hold_at_mode(path: Path) -> None:
    """Narrow one directory to 0700 when it is wider than that.

    Description: called on every level, because ``mkdir(parents=True)``
      ignores ``mode`` for the parents it creates and the process umask
      masks it for the leaf. Only narrows, and only when it has to, so a
      directory already at 0700 is not chmod'ed on every login.
    Inputs: path (Path) - a directory that exists.
    Output: None.
    Raises: OSError - the mode could not be read or changed.
    Example: _hold_at_mode(Path.home() / ".carnivore")
    """
    current = stat.S_IMODE(path.stat().st_mode)
    if current & 0o077:
        path.chmod(MANAGED_DIR_MODE)


def ensure_managed_dir(account_id: str) -> str:
    """Create this account's profile directory at 0700, idempotently.

    Description: creates ``~/.carnivore``, ``~/.carnivore/accounts`` and
      the account's own directory, and holds all three at 0700. Calling
      it twice creates nothing the second time and writes nothing inside
      the directory, so an existing login is untouched.

      **THE CALLER MUST RUN THIS BEFORE IT SPAWNS ANYTHING.** Codex does
      not create ``CODEX_HOME`` for you: its own documentation says the
      directory has to exist already. A build that spawned first would
      produce a login that fails for a reason nobody would look for.
    Inputs: account_id (str) - the account's own id, the validated slug.
    Output: str - the absolute path, the same string
      :func:`managed_dir_for` answers.
    Raises:
      ValueError: the id is not the validated slug shape.
      ManagedProfileError: a level of the tree is a symbolic link, the
        directory could not be created, its mode could not be held, or
        the leaf did not land under the managed root.
    Example: ensure_managed_dir("claude1")
    """
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
