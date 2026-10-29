
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

COMMITTED = "committed"

UNCHANGED = "unchanged"

STALE_REVISION = "stale_revision"

REJECTED_INVALID = "rejected_invalid"

NOTE_MAX_BYTES = 256 * 1024


class SessionNotesUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class NoteResult:

    status: str
    revision: int
    body: str
    updated_at: Optional[str] = None
    detail: Optional[str] = None

    def as_payload(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "status": self.status,
            "revision": self.revision,
            "body": self.body,
            "updated_at": self.updated_at,
        }
        if self.detail:
            body["detail"] = self.detail
        return body


def table_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_notes'"
    ).fetchone()
    return row is not None


def _require_table(conn: sqlite3.Connection) -> None:
    if not table_present(conn):
        raise SessionNotesUnavailable(
            "this datastore has no session_notes table; it predates schema v30"
        )


def read_note(conn: sqlite3.Connection, session_uuid: str) -> NoteResult:
    _require_table(conn)
    row = conn.execute(
        "SELECT body, revision, updated_at FROM session_notes WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        return NoteResult(status=UNCHANGED, revision=0, body="", updated_at=None)
    return NoteResult(
        status=UNCHANGED,
        revision=int(row[1]),
        body=str(row[0]),
        updated_at=None if row[2] is None else str(row[2]),
    )


def write_note(
    conn: sqlite3.Connection,
    session_uuid: str,
    body: str,
    expected_revision: int,
) -> NoteResult:
    _require_table(conn)
    size = len(body.encode("utf-8"))
    current = read_note(conn, session_uuid)
    if size > NOTE_MAX_BYTES:
        logger.info(
            "session_note_too_large",
            session_uuid=session_uuid,
            bytes=size,
            limit=NOTE_MAX_BYTES,
        )
        return NoteResult(
            status=REJECTED_INVALID,
            revision=current.revision,
            body=current.body,
            updated_at=current.updated_at,
            detail=(
                "this note is larger than the "
                f"{NOTE_MAX_BYTES // 1024} KiB a note may hold"
            ),
        )

    if expected_revision != current.revision:
        logger.info(
            "session_note_stale_revision",
            session_uuid=session_uuid,
            expected=expected_revision,
            current=current.revision,
        )
        return NoteResult(
            status=STALE_REVISION,
            revision=current.revision,
            body=current.body,
            updated_at=current.updated_at,
            detail=(
                "another computer saved this note first; the current "
                f"revision is {current.revision}"
            ),
        )

    if body == current.body:
        return NoteResult(
            status=UNCHANGED,
            revision=current.revision,
            body=current.body,
            updated_at=current.updated_at,
        )

    revision = current.revision + 1
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO session_notes (session_uuid, body, revision, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(session_uuid) DO UPDATE SET "
        "body = excluded.body, revision = excluded.revision, "
        "updated_at = excluded.updated_at",
        (session_uuid, body, revision, stamp),
    )
    logger.info(
        "session_note_committed",
        session_uuid=session_uuid,
        revision=revision,
        bytes=size,
    )
    return NoteResult(
        status=COMMITTED, revision=revision, body=body, updated_at=stamp
    )
