
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import structlog

from src.core import product_identity
from src.core.db import connect, get_schema_version, integrity_check

logger = structlog.get_logger()

BACKUP_PREFIX = product_identity.DB_BACKUP_PREFIX

BACKUP_SUFFIX = ".nobackup"

_RECOGNIZED_BACKUP_PREFIXES = (BACKUP_PREFIX,) + tuple(
    product_identity.LEGACY_DB_BACKUP_PREFIXES
)
BACKUP_NAME_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in _RECOGNIZED_BACKUP_PREFIXES) + r")"
    r"(?P<version>[^-]+)-(?P<stamp>\d{8}T\d{6}Z)"
    r"(?:-(?P<seq>\d+))?"
    r"(?:\.nobackup)?$"
)

KEEP_VERSIONS = 5
KEEP_DAYS = 3

_SIDECAR_SUFFIXES = ("-shm", "-wal")


@dataclass
class BackupResult:
    """The outcome of taking and verifying one backup. Three states.

    Description: ``verified`` is the only thing a caller may act on.
      ``taken`` distinguishes "the copy never happened" from "the copy
      happened and could not be trusted", which matters for the message
      the user sees but not for the decision, which is identical: do not
      migrate.
    Inputs (constructor): taken (bool), verified (bool), path (Path |
      None - the backup file, which is DELETED when verification fails so
      a bad copy cannot later be mistaken for a good one), reason (str |
      None - why it is not verified; None when verified is True).
    Output: a BackupResult instance.
    """

    taken: bool
    verified: bool
    path: Optional[Path] = None
    reason: Optional[str] = None

    @property
    def basename(self) -> Optional[str]:
        return None if self.path is None else self.path.name


def backup_filename(from_version: object, when: Optional[datetime] = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{BACKUP_PREFIX}{from_version}-{stamp}{BACKUP_SUFFIX}"


def take_backup(
    db_path: Path, state_dir: Path, from_version: int
) -> BackupResult:
    db_path = Path(db_path)
    state_dir = Path(state_dir)
    target = state_dir / backup_filename(from_version)

    if not db_path.exists():
        return BackupResult(
            taken=False,
            verified=False,
            reason=f"{db_path.name} does not exist, so there is nothing to back up",
        )
    target = _uniquify(target)

    try:
        with closing(connect(db_path, create=False)) as conn:
            conn.execute("VACUUM INTO ?", (str(target),))
    except Exception as exc:  # noqa: BLE001
        _remove_quietly(target)
        return BackupResult(
            taken=False,
            verified=False,
            reason=f"VACUUM INTO failed: {exc}",
        )

    verified, reason = verify_backup(target, from_version)
    if not verified:
        _remove_quietly(target)
        return BackupResult(taken=True, verified=False, path=target, reason=reason)

    logger.info(
        "db_backup_verified", path=target.name, from_version=from_version
    )
    return BackupResult(taken=True, verified=True, path=target)


def verify_backup(path: Path, expect_version: int) -> tuple:
    path = Path(path)
    if not path.exists():
        return False, f"{path.name} was not created"
    if path.stat().st_size == 0:
        return False, f"{path.name} is zero bytes"
    try:
        with closing(connect(path, create=False)) as conn:
            verdict = integrity_check(conn)
            if verdict != "ok":
                return False, f"{path.name} failed integrity_check: {verdict}"
            found = get_schema_version(conn)
    except Exception as exc:  # noqa: BLE001
        return False, f"{path.name} could not be opened for verification: {exc}"
    if found != expect_version:
        return False, (
            f"{path.name} records schema_version {found}, expected "
            f"{expect_version} - this copy is not a snapshot of the database "
            "about to be migrated"
        )
    return True, None


def list_backups(state_dir: Path) -> List[Path]:
    """List every recognised backup file, newest first.

    Description: recognised means matching BACKUP_NAME_RE. A file in the
      state dir with a similar-looking name that does not match is
      IGNORED rather than guessed at - retention must never delete
      something it could not positively identify as its own artifact.
    Inputs: state_dir (Path).
    Output: list[Path] - sorted by embedded timestamp, newest first.
    """
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        return []
    matched = [p for p in state_dir.iterdir() if BACKUP_NAME_RE.match(p.name)]
    return sorted(matched, key=_sort_key, reverse=True)


def _sidecars_of(path: Path) -> List[Path]:
    found = [path.with_name(path.name + suffix) for suffix in _SIDECAR_SUFFIXES]
    return [p for p in found if p.exists()]


def _orphan_sidecars(state_dir: Path) -> List[Path]:
    orphans: List[Path] = []
    for entry in state_dir.iterdir():
        for suffix in _SIDECAR_SUFFIXES:
            if entry.name.endswith(suffix):
                base = entry.name[: -len(suffix)]
                if BACKUP_NAME_RE.match(base) and not (state_dir / base).exists():
                    orphans.append(entry)
    return orphans


def prune_backups(
    state_dir: Path,
    keep_versions: int = KEEP_VERSIONS,
    keep_days: int = KEEP_DAYS,
    now: Optional[datetime] = None,
) -> List[Path]:
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        return []
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=keep_days)
    doomed: List[Path] = []
    for path in list_backups(state_dir)[keep_versions:]:
        stamp = _parse_stamp(path.name)
        if stamp is None or stamp >= cutoff:
            continue
        doomed.append(path)
        doomed.extend(_sidecars_of(path))
    doomed_set = set(doomed)
    doomed.extend(p for p in _orphan_sidecars(state_dir) if p not in doomed_set)
    deleted: List[Path] = []
    for path in doomed:
        try:
            path.unlink()
            deleted.append(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("db_backup_prune_failed", path=path.name, error=str(exc))
    if deleted:
        logger.info("db_backups_pruned", count=len(deleted))
    return deleted


def _uniquify(target: Path) -> Path:
    """Return a path that does not exist, adding a -N suffix if needed.

    Description: a prior backup is NEVER overwritten. When the natural
      name is taken (two migrations inside the same second, which a
      crash-loop produces), a numeric suffix is appended instead of
      failing - refusing to back up because a one-second-old backup
      exists would abort the retry that needs the backup most.
      THE SEQUENCE GOES BEFORE BACKUP_SUFFIX, NOT AFTER IT, AND BOTH
      REASONS ARE LOAD BEARING. Appending it to the whole name would
      produce "...Z.nobackup-2", which BACKUP_NAME_RE does not match - so
      the file would drop out of list_backups, out of retention and out of
      select_backup, invisibly - and which no ".nobackup" exclusion rule
      matches either, so the very copy the suffix exists to keep off-box
      would be the one that got shipped. A suffix that means something to
      other tools has to be the LAST thing in the name.
    Inputs: target (Path) - the natural, timestamped backup path.
    Output: Path - target, or the same name with "-2", "-3", ... inserted
      ahead of the suffix.
    Raises: RuntimeError - after 999 collisions, which cannot happen
      without something else being badly wrong.
    """
    if not target.exists():
        return target
    name = target.name
    stem, suffix = (
        (name[: -len(BACKUP_SUFFIX)], BACKUP_SUFFIX)
        if name.endswith(BACKUP_SUFFIX) else (name, "")
    )
    for seq in range(2, 1000):
        candidate = target.with_name(f"{stem}-{seq}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find a free backup name near {target}")


def _sort_key(path: Path) -> tuple:
    match = BACKUP_NAME_RE.match(path.name)
    if not match:
        return ("", 0)
    return (match.group("stamp"), int(match.group("seq") or 1))


def _parse_stamp(name: str) -> Optional[datetime]:
    match = BACKUP_NAME_RE.match(name)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _remove_quietly(path: Path) -> None:
    """Delete a file, ignoring its absence.

    Description: used to destroy an unverifiable backup so it cannot
      later be mistaken for a good one. A failure to delete is logged,
      not raised - the caller is already on an abort path.
    Inputs: path (Path).
    Output: None.
    """
    try:
        Path(path).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("db_backup_cleanup_failed", path=str(path), error=str(exc))


def sqlite_copy_is_wal_safe(conn: sqlite3.Connection) -> bool:
    """Report whether a connection's journal mode is WAL.

    Description: exists so a test (and a future CLI health check) can
      assert the pragma actually took, rather than assuming it did
      because the line is in the source.
    Inputs: conn (sqlite3.Connection).
    Output: bool - True when PRAGMA journal_mode reports "wal".
    """
    row = conn.execute("PRAGMA journal_mode").fetchone()
    return row is not None and str(row[0]).lower() == "wal"
