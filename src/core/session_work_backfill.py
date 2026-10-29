
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.claude_project_dirs import candidate_project_dirs
from src.core.db import DatastoreUnreadableError, connect, transaction
from src.core.subagents.files import last_record
from src.core.subagents.parent_index import parse_timestamp

logger = structlog.get_logger(__name__)

MAX_ROWS: int = 1000

# conversation id
_CLAUDE_FAMILIES = (DEFAULT_FAMILY,)


@dataclass(frozen=True)
class BackfillResult:

    considered: int
    stamped: int
    no_transcript: int
    no_work_line: int


def is_work(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    kind = record.get("type")
    if kind == "assistant":
        return True
    if kind != "user" or record.get("isMeta") is True:
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _transcript_for(
    conversation_uuid: str, working_dir: Optional[str], projects_dir: Optional[Path]
) -> Optional[Path]:
    """The row's transcript in its own project directories, or None."""
    if not working_dir:
        return None
    for directory in candidate_project_dirs(working_dir, projects_dir=projects_dir):
        candidate = directory / f"{conversation_uuid}.jsonl"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def last_work_at_from_transcript(path: Path) -> Optional[str]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            record, _capped = last_record(handle, size, skip=lambda r: not is_work(r))
    except OSError as exc:
        logger.debug("work_backfill_transcript_unreadable", error=str(exc))
        return None
    if not is_work(record):
        return None
    moment = parse_timestamp(record.get("timestamp"))
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def backfill_last_work_at(
    conn: sqlite3.Connection,
    *,
    projects_dir: Optional[Path] = None,
    max_rows: int = MAX_ROWS,
) -> BackfillResult:
    rows = conn.execute(
        "SELECT id, claude_session_uuid, working_dir FROM sessions "
        "WHERE last_work_at IS NULL AND claude_session_uuid IS NOT NULL "
        "AND claude_session_uuid != '' "
        "AND (agent_family IS NULL OR agent_family IN (%s)) "
        "ORDER BY id LIMIT ?" % ",".join("?" * len(_CLAUDE_FAMILIES)),
        (*_CLAUDE_FAMILIES, max_rows),
    ).fetchall()
    writes: List[Tuple[str, int]] = []
    no_transcript = no_work = 0
    for row_id, conversation_uuid, working_dir in rows:
        path = _transcript_for(conversation_uuid, working_dir, projects_dir)
        if path is None:
            no_transcript += 1
            continue
        value = last_work_at_from_transcript(path)
        if value is None:
            no_work += 1
            continue
        writes.append((value, int(row_id)))
    stamped = 0
    if writes:
        with transaction(conn):
            for value, row_id in writes:
                cur = conn.execute(
                    "UPDATE sessions SET last_work_at = ? "
                    "WHERE id = ? AND last_work_at IS NULL",
                    (value, row_id),
                )
                stamped += cur.rowcount
    return BackfillResult(len(rows), stamped, no_transcript, no_work)


def run_boot_backfill(db_path: Path) -> Optional[BackfillResult]:
    try:
        with closing(connect(db_path, create=False)) as conn:
            result = backfill_last_work_at(conn)
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("work_backfill_failed", error=str(exc),
                       error_type=type(exc).__name__)
        return None
    logger.info(
        "work_backfill_boot",
        considered=result.considered,
        stamped=result.stamped,
        no_transcript=result.no_transcript,
        no_work_line=result.no_work_line,
    )
    return result
