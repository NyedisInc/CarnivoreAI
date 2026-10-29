
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCES,
    SESSION_FORK_KIND_BACKGROUND,
    SESSION_FORK_KIND_FORK,
    SESSION_FORK_KIND_UNKNOWN,
    SESSION_FORK_KINDS,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
)
from src.core.session_lineage_divergence import (
    classify_uuid_divergence,
    mints_a_row,
)
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_store import get_instance, sessions_table_ready
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

from src.core import debug_trace  # noqa: E402


LINEAGE_BOUND = "bound"

LINEAGE_CONTINUED = "continued"

LINEAGE_FORKED = "forked"

LINEAGE_SIBLING = "sibling"

# COULD NOT EVALUATE
# could not
LINEAGE_UNRESOLVED = "unresolved"

LINEAGE_NO_WRITE: Tuple[str, ...] = (
    LINEAGE_CONTINUED,
    LINEAGE_SIBLING,
    LINEAGE_UNRESOLVED,
)


@dataclass(frozen=True)
class LineageResult:
    """What one :func:`record_claude_session` call did to the table.

    Description: an explicit five-name, three-class outcome so a caller
      can tell a bind from a fork from a no-op from a could-not-evaluate.
      A bare bool here would make "we could not find the row" and "nothing
      needed doing" the same answer, which is the exact collapse that
      turns missing lineage into invisible missing lineage.
    Inputs (constructor): outcome (str) - one of ``LINEAGE_BOUND``,
      ``LINEAGE_CONTINUED``, ``LINEAGE_FORKED``, ``LINEAGE_SIBLING``,
      ``LINEAGE_UNRESOLVED``.
      row_id (int | None) - the sessions.id the uuid now lives on; None
      only when unresolved. parent_row_id (int | None) - set only on a
      fork. fork_kind (str | None) - set only on a fork. detail (str |
      None) - human-readable reason, always set when unresolved.
    Output: a LineageResult instance.
    Example: record_claude_session(...).outcome  # 'forked'
    """

    outcome: str
    row_id: Optional[int] = None
    parent_row_id: Optional[int] = None
    fork_kind: Optional[str] = None
    detail: Optional[str] = None

    @property
    def wrote(self) -> bool:
        return self.outcome not in LINEAGE_NO_WRITE


def classify_fork_kind(source: Optional[str]) -> str:
    if isinstance(source, str) and source in SESSION_FORK_KINDS:
        return source
    return SESSION_FORK_KIND_UNKNOWN


def row_for_claude_uuid(
    conn: sqlite3.Connection, claude_uuid: str
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return None
    if not claude_uuid:
        return None
    row = conn.execute(
        "SELECT * FROM sessions WHERE claude_session_uuid = ? ORDER BY id LIMIT 1",
        (claude_uuid,),
    ).fetchone()
    return dict(row) if row is not None else None


def lineage_head(
    conn: sqlite3.Connection, root_id: int
) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (root_id,)).fetchone()
    current = dict(row) if row is not None else {"id": root_id}
    for _ in range(_MAX_LINEAGE_DEPTH):
        child = conn.execute(
            "SELECT * FROM sessions WHERE parent_session_id = ? "
            "AND (fork_kind IS NULL OR fork_kind != ?) "
            "AND tmux_created_epoch IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (int(current["id"]), SESSION_FORK_KIND_BACKGROUND),
        ).fetchone()
        if child is None:
            return current
        current = dict(child)
    logger.warning(
        "lineage_walk_depth_capped",
        root_id=root_id,
        cap=_MAX_LINEAGE_DEPTH,
        note=(
            "stopped walking and used the deepest row reached. The parent "
            "chain is longer than any real session history, so it is being "
            "reported rather than followed"
        ),
    )
    return current


_MAX_LINEAGE_DEPTH = 512


def lineage_chain(
    conn: sqlite3.Connection, row_id: int
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return []
    node = dict(row)
    for _ in range(_MAX_LINEAGE_DEPTH):
        parent_id = node.get("parent_session_id")
        if parent_id is None:
            break
        parent = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (int(parent_id),)
        ).fetchone()
        if parent is None:
            break
        node = dict(parent)
    chain = [node]
    for _ in range(_MAX_LINEAGE_DEPTH):
        child = conn.execute(
            "SELECT * FROM sessions WHERE parent_session_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (int(chain[-1]["id"]),),
        ).fetchone()
        if child is None:
            break
        chain.append(dict(child))
    return chain


def record_claude_session(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    claude_uuid: str,
    source: Optional[str] = None,
    title: Optional[str] = None,
    pane_left_previous: bool = True,
    uuid_source: str = SESSION_CLAUDE_UUID_SOURCE_HOOK,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> LineageResult:
    stamp = now or utc_now()

    debug_trace.trace(
        "lineage.record.input",
        socket=socket,
        name=name,
        epoch=epoch,
        has_claude_uuid=bool(claude_uuid),
        source=source,
    )

    if not sessions_table_ready(conn):
        return LineageResult(
            outcome=LINEAGE_UNRESOLVED,
            detail="the datastore has no sessions table (pre-v2)",
        )
    if not claude_uuid:
        return LineageResult(
            outcome=LINEAGE_UNRESOLVED,
            detail="the hook payload carried no session id",
        )
    if uuid_source not in SESSION_CLAUDE_UUID_SOURCES:
        logger.warning(
            "claude_uuid_source_unknown",
            requested_source=uuid_source,
            tmux_name=name,
        )
        uuid_source = SESSION_CLAUDE_UUID_SOURCE_HOOK

    known = row_for_claude_uuid(conn, claude_uuid)
    if known is not None:
        _record_claude_title(conn, known, title, stamp)
        return LineageResult(
            outcome=LINEAGE_CONTINUED,
            row_id=int(known["id"]),
            detail=f"session {claude_uuid} is already recorded",
        )

    anchor = get_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
    if anchor is None:
        return LineageResult(
            outcome=LINEAGE_UNRESOLVED,
            detail=(
                "no sessions row carries this tmux instance triple "
                f"({socket}/{name}/{epoch})"
            ),
        )

    head = lineage_head(conn, int(anchor["id"]))
    head_uuid = head.get("claude_session_uuid")

    if not head_uuid:
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ?, "
            "claude_session_uuid_source = ?, updated_at = ? "
            "WHERE id = ?",
            (claude_uuid, uuid_source, stamp, int(head["id"])),
        )
        _record_claude_title(conn, head, title, stamp)
        logger.info(
            "claude_session_bound",
            row_id=int(head["id"]),
            tmux_name=name,
            source=source,
            uuid_source=uuid_source,
        )
        return LineageResult(
            outcome=LINEAGE_BOUND,
            row_id=int(head["id"]),
        )

    divergence = classify_uuid_divergence(source)
    if not mints_a_row(divergence):
        logger.info(
            "claude_sibling_session_ignored",
            row_id=int(head["id"]),
            tmux_name=name,
            source=source,
            head_claude_uuid=head_uuid,
            sibling_claude_uuid=claude_uuid,
        )
        return LineageResult(
            outcome=LINEAGE_SIBLING,
            row_id=int(head["id"]),
            detail=(
                f"session {claude_uuid} arrived under source '{source}', a "
                "process boot, so it is another claude running in this pane "
                f"rather than a fork of {head_uuid}"
            ),
        )

    fork_kind = classify_fork_kind(source)
    if fork_kind == SESSION_FORK_KIND_FORK and not pane_left_previous:
        fork_kind = SESSION_FORK_KIND_BACKGROUND
    columns = [
        "session_uuid",
        "tmux_socket",
        "tmux_name",
        "tmux_created_epoch",
        "origin",
        "project_id",
        "project_attribution",
        "working_dir",
        "agent_type",
        "agent_family",
        "agent_family_source",
        "claude_session_uuid",
        "claude_session_uuid_source",
        "parent_session_id",
        "fork_kind",
        "lifecycle",
        "lifecycle_checked_at",
        "lifecycle_source",
        "title",
        "claude_title",
        "created_at",
        "updated_at",
    ]
    values: List[Any] = [
        _new_row_uuid(),
        anchor.get("tmux_socket") or socket,
        anchor.get("tmux_name") or name,
        None,
        anchor.get("origin"),
        anchor.get("project_id"),
        anchor.get("project_attribution"),
        anchor.get("working_dir"),
        anchor.get("agent_type"),
        anchor.get("agent_family"),
        anchor.get("agent_family_source"),
        claude_uuid,
        uuid_source,
        int(head["id"]),
        fork_kind,
        SESSION_LIFECYCLE_STOPPED,
        stamp,
        SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
        anchor.get("title"),
        title,
        stamp,
        stamp,
    ]
    if "host_key" in anchor:
        columns.append("host_key")
        values.append(anchor["host_key"])
    placeholders = ", ".join("?" for _ in columns)
    cursor = conn.execute(
        f"INSERT INTO sessions ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    logger.info(
        "claude_session_forked",
        row_id=int(cursor.lastrowid),
        parent_row_id=int(head["id"]),
        fork_kind=fork_kind,
        tmux_name=name,
        source=source,
    )
    return LineageResult(
        outcome=LINEAGE_FORKED,
        row_id=int(cursor.lastrowid),
        parent_row_id=int(head["id"]),
        fork_kind=fork_kind,
    )


def _new_row_uuid() -> str:
    from src.core.session_identity import new_session_uuid

    return new_session_uuid()


def _record_claude_title(
    conn: sqlite3.Connection,
    row: Dict[str, Any],
    title: Optional[str],
    stamp: str,
) -> None:
    if not title or row.get("claude_title") == title:
        return
    conn.execute(
        "UPDATE sessions SET claude_title = ?, updated_at = ? WHERE id = ?",
        (title, stamp, int(row["id"])),
    )
