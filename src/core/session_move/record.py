
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.db import table_exists, transaction
from src.core.session_project_binding import columns_to_write, resolve_project_binding

logger = structlog.get_logger()


class SessionMoveRecordError(Exception):
    """The row could not be written with a project pair the probe agrees with."""


@dataclass(frozen=True)
class MovedRow:

    working_dir: str
    project_id: int
    attribution: str
    project_created: bool
    conversation_rows: int


def write_moved_row(conn: sqlite3.Connection, *, row_id: int, destination: str, stored_project_id: Optional[int],
                    claude_session_uuid: Optional[str], now: str) -> MovedRow:
    with transaction(conn):
        binding = resolve_project_binding(conn, destination, stored_project_id=None, allow_create=True, now=now,
                                          display_name=os.path.basename(destination))
        project_id, attribution = columns_to_write(binding, None)
        if project_id is None or attribution is None:
            raise SessionMoveRecordError(f"no project resolved for {destination}: {binding.detail or binding.rule}")
        conn.execute("UPDATE sessions SET working_dir = ?, project_id = ?, project_attribution = ?, updated_at = ? "
                     "WHERE id = ?", (destination, project_id, attribution, now, row_id))
        index_rows = 0
        if claude_session_uuid and table_exists(conn, "conversation_index"):
            name_row = conn.execute("SELECT display_name FROM projects WHERE id = ?", (project_id,)).fetchone()
            index_rows = conn.execute(
                "UPDATE conversation_index SET working_dir = ?, project_id = ?, project_name = ?, updated_at = ? "
                "WHERE conversation_id = ?",
                (destination, project_id, name_row[0] if name_row else "", now, claude_session_uuid)).rowcount
    logger.info("session_move_row_written", row_id=row_id, working_dir=destination, project_id=project_id,
                was_project_id=stored_project_id, project_created=binding.created_project, index_rows=index_rows)
    return MovedRow(working_dir=destination, project_id=int(project_id), attribution=str(attribution),
                    project_created=bool(binding.created_project), conversation_rows=int(index_rows))
