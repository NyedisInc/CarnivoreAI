
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

from src.core.db_models import TRAIL_STATUS_INTERRUPTED, TRAIL_STATUS_STARTED
from src.core.trail_entry import (
    FIELD_ORDER,
    REQUIRED_FIELDS,
    TrailEntry,
    new_entry_uuid,
    utc_now,
)
from src.core.trail_reader import (
    TRAIL_READ_ABSENT,
    TRAIL_READ_OK,
    TRAIL_READ_TRUNCATED_TAIL,
    TRAIL_READ_UNREADABLE,
    TrailReadResult,
    find_unclosed,
    prior_interrupt_uuid,
    read_trail,
)

logger = structlog.get_logger()

TRAIL_FILENAME = "migration_trail.jsonl"

__all__ = [
    "FIELD_ORDER",
    "REQUIRED_FIELDS",
    "TRAIL_FILENAME",
    "TRAIL_READ_ABSENT",
    "TRAIL_READ_OK",
    "TRAIL_READ_TRUNCATED_TAIL",
    "TRAIL_READ_UNREADABLE",
    "MigrationTrail",
    "TrailEntry",
    "TrailReadResult",
    "find_unclosed",
    "prior_interrupt_uuid",
    "new_entry_uuid",
    "read_trail",
    "utc_now",
]


class MigrationTrail:

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / TRAIL_FILENAME

    def read(self) -> TrailReadResult:
        return read_trail(self.path)

    def append(self, entry: TrailEntry) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = entry.to_line().encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_dir()

    def _fsync_dir(self) -> None:
        try:
            dir_fd = os.open(str(self.state_dir), os.O_RDONLY)
        except OSError as exc:
            logger.debug("trail_dir_fsync_open_failed", error=str(exc))
            return
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            logger.debug("trail_dir_fsync_failed", error=str(exc))
        finally:
            os.close(dir_fd)

    def open_step(
        self,
        kind: str,
        from_version: Optional[str],
        to_version: Optional[str],
        app_version: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> TrailEntry:
        entry = TrailEntry(
            entry_uuid=new_entry_uuid(),
            kind=kind,
            status=TRAIL_STATUS_STARTED,
            started_at=utc_now(),
            from_version=from_version,
            to_version=to_version,
            app_version=app_version,
            detail=detail,
        )
        self.append(entry)
        return entry

    def close_step(
        self,
        started: TrailEntry,
        status: str,
        backup_path: Optional[str] = None,
        backup_verified: Optional[int] = None,
        error: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> TrailEntry:
        entry = TrailEntry(
            entry_uuid=started.entry_uuid,
            kind=started.kind,
            status=status,
            started_at=started.started_at,
            from_version=started.from_version,
            to_version=started.to_version,
            completed_at=utc_now(),
            backup_path=backup_path,
            backup_verified=backup_verified,
            app_version=started.app_version,
            error=error,
            detail=detail if detail is not None else started.detail,
        )
        self.append(entry)
        return entry

    def mark_interrupted(self, unclosed: TrailEntry) -> TrailEntry:
        reason = (
            "trail line was truncated mid-write"
            if unclosed.recovered_partial
            else "no closing line followed this started line"
        )
        return self.close_step(
            unclosed,
            TRAIL_STATUS_INTERRUPTED,
            error=None,
            detail=(
                f"detected at startup: {reason}. The step announced itself "
                "and never recorded an outcome."
            ),
        )
