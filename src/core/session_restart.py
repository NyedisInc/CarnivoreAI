"""RESTARTING a stopped session: what it carries, and what it cannot be.

THE BUG THIS EXISTS FOR. The launchpad's RESTART control on a stopped
session built its request from ``working_dir`` and ``agent_type`` and
nothing else. The row's TITLE was never even put into the button's
markup, and its ``session_uuid`` was in the dataset but never passed to
the handler. So restarting a session the user had named, and had been
talking to for hours, produced an unnamed blank console in the right
directory - it discarded identity the client was already holding.

A RESTART NEEDS A NEW TMUX SESSION, BUT NOT A NEW ROW. SUPERSEDED, and
the correction is the whole point of this module. ``POST
/sessions/respawn`` puts a process back into a tmux session that still
EXISTS, and it works because ``remain-on-exit`` kept the pane alive. A
session whose tmux is gone has none of that, so a new tmux session must
be spawned and its ``#{session_created}`` is necessarily a new epoch.
This module used to conclude from that that a new ROW must be inserted
too, because the identity triple ``(tmux_socket, tmux_name,
tmux_created_epoch)`` could not match the old row "and must not be made
to". That conclusion was wrong, and it did real damage.

The triple is not the session's identity - it is the identity of the
TMUX INSTANCE the session is currently running on. The session's own
identity is ``sessions.id`` and its ``session_uuid``, and those are what
every other table references: ``parent_session_id``,
``transcript_archives.root_session_id`` and
``transcript_root_decisions.root_session_id`` all point at the id, and
nothing anywhere keys off the triple except the reconciler that reads
tmux. So the triple can simply be MOVED onto the existing row - see
:func:`rebind_instance` - and every reference survives untouched.

WHAT INSERTING A SECOND ROW ACTUALLY COST. The user's title, their
conversation, their group membership, their archive roots and their
lineage all stayed on the row that had been left behind, while the
session they were now looking at was a stranger wearing a copied name.
Both rows then rendered - the live one under running sessions and the
abandoned one under recent - so every restart permanently doubled the
session list, and a "this replaced an earlier session" disclosure had to
be invented to explain a duplicate that should never have existed. The
duplicate was not a display problem. It was this INSERT.

WHY THE REPLACEMENT NOW RESUMES WITH A BARE ``--resume``. SUPERSEDED
too, and for the same reason. ``--fork-session`` was there because two
rows would otherwise have carried one ``claude_session_uuid``, which
``ux_sessions_claude_uuid`` forbids as a UNIQUE partial index. With one
row there is no second row to collide with, so the flag has nothing left
to prevent. Removing it matters beyond tidiness: a fork MINTS A NEW uuid,
so a restarted session used to stop being the conversation the user had
been having and become a copy of it. A bare resume keeps one
conversation, on one row, under one uuid. See :func:`resume_arguments`.

THERE IS NO LINEAGE STAMP ON A RESTART ANY MORE. ``parent_session_id``
and ``fork_kind`` describe one conversation coming out of ANOTHER one,
which is exactly what the explicit FORK button does and what
``session_fork`` still records. A restart produces no second session, so
there is no relationship to record - the row simply continues. Writing a
self-referential parent link would be inventing a relationship to
describe a row's own history.

THE TITLE IS CARRIED because it is never touched: it is a column on the
row being reused, and so are the pins, the unread counts and the
conversation link.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.session_label import label_from_tmux_name
from src.core.session_store import sessions_table_ready

logger = structlog.get_logger()

RESTART_RESUMABLE = "resumable"

RESTART_NO_CONVERSATION = "no-conversation"

RESTART_CONVERSATION_MISSING = "conversation-missing"

# COULD NOT EVALUATE
RESTART_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RestartSource:

    outcome: str
    parent_id: Optional[int] = None
    claude_session_uuid: Optional[str] = None
    conversation_row_id: Optional[int] = None
    title: Optional[str] = None
    working_dir: Optional[str] = None
    agent_type: Optional[str] = None
    model: Optional[str] = None
    project_id: Optional[int] = None
    detail: Optional[str] = None
    launch_record: Optional[str] = None


def _configured_wrappers() -> list:
    """The configured wrappers (profile ids included) that ``resolve_agent_type`` reads.

    Output: list - ``[]`` when config.json cannot be read, so a degraded environment resolves by family name alone.
    Example: resolve_agent_type("rigcodex", _configured_wrappers())
    """
    from src.config import settings

    try:
        return list(settings.load_auth_config().agents.wrappers)
    except (OSError, ValueError) as exc:
        logger.warning("restart_wrappers_unreadable", error=str(exc))
        return []


def resolve_restart_source(
    conn: sqlite3.Connection, *, session_uuid: str, check_transcript: bool = True
) -> RestartSource:
    if not sessions_table_ready(conn):
        return RestartSource(
            RESTART_UNRESOLVED,
            detail="datastore predates the sessions table",
        )
    if not session_uuid:
        return RestartSource(
            RESTART_UNRESOLVED,
            detail="no session_uuid was supplied, so no row can be named",
        )
    row = conn.execute(
        "SELECT id, claude_session_uuid, working_dir, title, tmux_name, "
        "agent_type, model, project_id, launch_record FROM sessions "
        "WHERE session_uuid = ? LIMIT 1",
        (session_uuid,),
    ).fetchone()
    if row is None:
        return RestartSource(
            RESTART_UNRESOLVED,
            detail=f"no stored session with session_uuid {session_uuid!r}",
        )
    data: Dict[str, Any] = dict(row)
    title = data.get("title") or label_from_tmux_name(data.get("tmux_name"))

    from src.core.session_lineage import lineage_head

    head = lineage_head(conn, int(data["id"]))
    head_id = int(head.get("id") or data["id"])
    uuid = head.get("claude_session_uuid") or data.get("claude_session_uuid")
    conversation_row_id = head_id if head_id != int(data["id"]) else None
    if not uuid:
        return RestartSource(
            RESTART_NO_CONVERSATION,
            parent_id=data["id"],
            title=title,
            working_dir=data.get("working_dir"),
            agent_type=data.get("agent_type"),
            model=data.get("model"),
            project_id=data.get("project_id"),
            launch_record=data.get("launch_record"),
            detail=(
                "this session never recorded a Claude conversation, so "
                "there is nothing to resume. The replacement keeps the "
                "name, directory and agent, and starts a NEW conversation."
            ),
        )
    from src.core.agent_families import resolve_agent_type
    from src.core.session_transcript_presence import family_conversation_presence

    presence = family_conversation_presence(
        resolve_agent_type(data.get("agent_type"), _configured_wrappers())[0].name,
        uuid,
        working_dir=data.get("working_dir"),
    ) if check_transcript else None
    if presence is not None and presence.missing:
        logger.warning(
            "restart_conversation_transcript_missing",
            session_id=int(data["id"]),
            conversation_row_id=conversation_row_id,
            claude_session_uuid=uuid,
            note=(
                "the row names a conversation with no transcript on disk; "
                "resuming it would spawn a pane that exits immediately"
            ),
        )
        return RestartSource(
            RESTART_CONVERSATION_MISSING,
            parent_id=data["id"],
            claude_session_uuid=uuid,
            conversation_row_id=conversation_row_id,
            title=title,
            working_dir=data.get("working_dir"),
            agent_type=data.get("agent_type"),
            model=data.get("model"),
            project_id=data.get("project_id"),
            detail=presence.detail,
        )

    return RestartSource(
        RESTART_RESUMABLE,
        parent_id=data["id"],
        claude_session_uuid=uuid,
        conversation_row_id=conversation_row_id,
        title=title,
        working_dir=data.get("working_dir"),
        agent_type=data.get("agent_type"),
        model=data.get("model"),
        project_id=data.get("project_id"),
        launch_record=data.get("launch_record"),
    )


REBIND_DONE = "rebound"

REBIND_CONFLICT = "conflict"

# COULD NOT EVALUATE
# could not
REBIND_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RebindResult:

    outcome: str
    session_uuid: Optional[str] = None
    detail: Optional[str] = None

    @property
    def rebound(self) -> bool:
        return self.outcome == REBIND_DONE


def rebind_instance(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    socket: str,
    name: str,
    epoch: int,
    tmux_session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    lifecycle_source: Optional[str] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> RebindResult:
    from src.core.db_models import SESSION_LIFECYCLE_RUNNING
    from src.core.trail_entry import utc_now

    stamp = now or utc_now()

    if not sessions_table_ready(conn):
        return RebindResult(
            REBIND_UNRESOLVED,
            detail="datastore predates the sessions table",
        )

    row = conn.execute(
        "SELECT session_uuid FROM sessions WHERE id = ? LIMIT 1", (row_id,)
    ).fetchone()
    if row is None:
        return RebindResult(
            REBIND_UNRESOLVED,
            detail=f"no session row with id {row_id} to reuse",
        )
    session_uuid = row["session_uuid"] if not isinstance(row, tuple) else row[0]

    scope_sql, scope_params = host_scope(conn, host_key)
    clash = conn.execute(
        "SELECT id FROM sessions WHERE tmux_socket = ? AND tmux_name = ? "
        f"AND tmux_created_epoch = ? AND id != ?{scope_sql} LIMIT 1",
        (socket, name, int(epoch), row_id, *scope_params),
    ).fetchone()
    if clash is not None:
        other = clash["id"] if not isinstance(clash, tuple) else clash[0]
        logger.warning(
            "restart_rebind_conflict",
            reused_session_id=row_id,
            conflicting_session_id=other,
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            note=(
                "another row already holds this tmux instance; nothing "
                "written, the caller records the instance normally"
            ),
        )
        return RebindResult(
            REBIND_CONFLICT,
            detail=(
                f"session row {other} already describes this tmux "
                f"instance, so row {row_id} was left alone"
            ),
        )

    sets = [
        "tmux_socket = ?",
        "tmux_name = ?",
        "tmux_created_epoch = ?",
        "tmux_session_id = ?",
        "lifecycle = ?",
        "lifecycle_source = ?",
        "lifecycle_checked_at = ?",
        "last_seen_running_at = ?",
        "activity_state = NULL",
        "activity_state_at = NULL",
        "archived_at = NULL",
        "updated_at = ?",
    ]
    values: list = [
        socket,
        name,
        int(epoch),
        tmux_session_id,
        SESSION_LIFECYCLE_RUNNING,
        lifecycle_source,
        stamp,
        stamp,
        stamp,
    ]
    if working_dir is not None:
        sets.insert(4, "working_dir = ?")
        values.insert(4, working_dir)

    values.append(row_id)
    conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", values
    )
    logger.info(
        "restart_rebound_in_place",
        session_id=row_id,
        session_uuid=session_uuid,
        tmux_socket=socket,
        tmux_name=name,
        tmux_created_epoch=int(epoch),
        tmux_session_id=tmux_session_id,
        note=(
            "same row, new tmux instance: session_uuid, title, "
            "conversation, lineage, pins and unread all ride on the row "
            "and are untouched. activity_state cleared as stale"
        ),
    )
    return RebindResult(REBIND_DONE, session_uuid=session_uuid)


def resume_arguments(claude_session_uuid: str, *, family: Optional[str] = None) -> list:
    from src.core.attention.evidence import FAMILY_CODEX

    if family == FAMILY_CODEX:
        return ["resume", claude_session_uuid]
    return ["--resume", claude_session_uuid]
