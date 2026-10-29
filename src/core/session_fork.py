
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

from src.core.db_models import SESSION_FORK_KIND_FORK
from src.core.session_label import label_from_tmux_name
from src.core.session_store import sessions_table_ready
from src.core.trail_entry import utc_now
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

FORK_SUFFIX = "(fork)"

FORK_READY = "ready"

FORK_NO_CONVERSATION = "no-conversation"

FORK_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ForkSource:

    outcome: str
    parent_id: Optional[int] = None
    claude_session_uuid: Optional[str] = None
    working_dir: Optional[str] = None
    label: Optional[str] = None
    agent_type: Optional[str] = None
    model: Optional[str] = None
    project_id: Optional[int] = None
    detail: Optional[str] = None
    launch_record: Optional[str] = None


def fork_label(parent_label: Optional[str]) -> str:
    base = (parent_label or "").strip()
    return f"{base}{FORK_SUFFIX}" if base else FORK_SUFFIX


def resolve_fork_source(
    conn: sqlite3.Connection, *, socket: str, tmux_name: str, host_key: str = LOCAL_HOST_KEY
) -> ForkSource:
    if not sessions_table_ready(conn):
        return ForkSource(FORK_UNRESOLVED, detail="datastore predates the sessions table")
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT id, claude_session_uuid, working_dir, title, tmux_name, "
        "agent_type, model, project_id, launch_record FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch IS NOT NULL "
        "ORDER BY tmux_created_epoch DESC LIMIT 1",
        (socket, *scope_params, tmux_name),
    ).fetchone()
    if row is None:
        return ForkSource(
            FORK_UNRESOLVED,
            detail=f"no anchor row for {tmux_name!r} on socket {socket!r}",
        )
    data: Dict[str, Any] = dict(row)
    uuid = data.get("claude_session_uuid")
    if not uuid:
        return ForkSource(
            FORK_NO_CONVERSATION,
            parent_id=data["id"],
            label=data.get("title") or label_from_tmux_name(data.get("tmux_name")),
            detail=(
                "this session has no recorded Claude conversation yet, so there "
                "is nothing to resume. Forking it would start a NEW conversation "
                "wearing a fork label."
            ),
        )
    return ForkSource(
        FORK_READY,
        parent_id=data["id"],
        claude_session_uuid=uuid,
        working_dir=data.get("working_dir"),
        label=data.get("title") or label_from_tmux_name(data.get("tmux_name")),
        agent_type=data.get("agent_type"),
        model=data.get("model"),
        project_id=data.get("project_id"),
        launch_record=data.get("launch_record"),
    )


def fork_arguments(claude_session_uuid: str) -> list:
    return ["--resume", claude_session_uuid, "--fork-session"]


def mark_as_fork(
    conn: sqlite3.Connection,
    *,
    child_session_uuid: str,
    parent_id: int,
    now: Optional[str] = None,
) -> bool:
    if not sessions_table_ready(conn):
        return False
    row = conn.execute(
        "SELECT parent_session_id FROM sessions WHERE session_uuid = ?",
        (child_session_uuid,),
    ).fetchone()
    if row is None:
        logger.warning("fork_child_row_missing", child=child_session_uuid)
        return False
    if row["parent_session_id"] is not None:
        logger.warning(
            "fork_child_already_has_parent",
            child=child_session_uuid,
            existing=row["parent_session_id"],
        )
        return False
    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET parent_session_id = ?, fork_kind = ?, updated_at = ? "
        "WHERE session_uuid = ? AND parent_session_id IS NULL",
        (parent_id, SESSION_FORK_KIND_FORK, stamp, child_session_uuid),
    )
    _record_spawn_edge(conn, parent_id, child_session_uuid, stamp)
    logger.info("fork_recorded", child=child_session_uuid, parent_id=parent_id)
    return True


def _record_spawn_edge(conn: sqlite3.Connection, parent_id: int, child_session_uuid: str, stamp: str) -> None:
    from src.core.lineage import constants as LK
    from src.core.lineage import graph

    if not graph.ready(conn):
        return
    parent = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (parent_id,)).fetchone()
    if parent is None or not parent[0]:
        return
    graph.add_edge(conn, LK.NODE_SESSION, parent[0], LK.NODE_SESSION, child_session_uuid, LK.KIND_SPAWNED_BY,
                   created_at=stamp)


def children_of(conn: sqlite3.Connection, parent_id: int) -> list:
    if not sessions_table_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM sessions WHERE parent_session_id = ? ORDER BY id DESC",
            (parent_id,),
        ).fetchall()
    ]


def newest_anchor_uuid(
    conn: sqlite3.Connection, *, socket: str, tmux_name: str, host_key: str = LOCAL_HOST_KEY
) -> Optional[str]:
    if not sessions_table_ready(conn):
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT session_uuid FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch IS NOT NULL "
        "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
        (socket, *scope_params, tmux_name),
    ).fetchone()
    return row["session_uuid"] if row else None


def stamp_fork_child(db_path, *, socket: str, child_tmux: str, parent_id: int, label: str,
                     resumed_conversation: Optional[str] = None) -> bool:
    from contextlib import closing

    from src.core.db import connect, transaction
    from src.core.session_label import set_label_for_instance

    with closing(connect(db_path, create=False)) as conn:
        child_uuid = newest_anchor_uuid(conn, socket=socket, tmux_name=child_tmux or "")
        if not child_uuid:
            return False
        row = conn.execute(
            "SELECT tmux_created_epoch FROM sessions WHERE session_uuid = ?", (child_uuid,)
        ).fetchone()
        child_epoch = row["tmux_created_epoch"] if row else None
        with transaction(conn):
            marked = mark_as_fork(conn, child_session_uuid=child_uuid, parent_id=parent_id)
            set_label_for_instance(conn, socket=socket, name=child_tmux or "", epoch=child_epoch, label=label)
            if marked and resumed_conversation:
                _add_resumed_edge(conn, resumed_conversation, child_uuid)
            return marked


def _add_resumed_edge(conn: sqlite3.Connection, conversation_id: str, child_session_uuid: str) -> None:
    from src.core.lineage import constants as LK
    from src.core.lineage import graph as lineage_graph

    if lineage_graph.ready(conn):
        lineage_graph.add_edge(conn, LK.NODE_CONVERSATION, conversation_id, LK.NODE_SESSION, child_session_uuid,
                               LK.KIND_FORK)


@dataclass(frozen=True)
class ForkChild:

    session: Any
    recorded: bool
    stamp_error: Optional[BaseException] = None


async def spawn_fork_child(manager: Any, *, source: Dict[str, Any], label: str, project_name: str,
                           agent_extra_args: list, db_path: Any, socket: str,
                           resumed_conversation: Optional[str] = None) -> ForkChild:
    import asyncio
    import uuid as uuid_module

    from src.core.db import DatastoreUnreadableError

    child = await manager.create_session(
        session_id=f"ses_{uuid_module.uuid4().hex[:8]}", working_dir=source["working_dir"], project_name=project_name,
        agent_type=source["agent_type"], model=source["model"], agent_extra_args=agent_extra_args, label=label)
    try:
        recorded = bool(await asyncio.to_thread(
            stamp_fork_child, db_path, socket=socket, child_tmux=getattr(child, "tmux_session", None) or "",
            parent_id=source["id"], label=label, resumed_conversation=resumed_conversation))
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        return ForkChild(session=child, recorded=False, stamp_error=exc)
    return ForkChild(session=child, recorded=recorded)
