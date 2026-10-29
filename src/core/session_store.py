
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.db_reuse.executor import Executor

import structlog

from src.core.companion_shell.rows import exclude_clause
from src.core.db import column_exists, table_exists
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.sessions import errors as session_errors
from src.core.db_models import (
    DEFAULT_TMUX_SOCKET,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_UNKNOWN,
    SESSION_ORIGIN_OBSERVED,
    SESSION_OWNED_ORIGINS,
)
from src.core.session_kind import KIND_AUTOMATED as SESSION_KIND_AUTOMATED

logger = structlog.get_logger()

SESSIONS_TABLE = "sessions"
PROJECTS_TABLE = "projects"


class SessionInstanceMismatchError(LookupError):
    pass


class SessionNotFoundError(session_errors.SessionNotFound):
    pass

def sessions_table_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, SESSIONS_TABLE)


def _project_join_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, PROJECTS_TABLE) and column_exists(
        conn, SESSIONS_TABLE, "project_id"
    )


def get_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return None
    if epoch is None:
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT * FROM sessions WHERE tmux_socket = ? AND tmux_name = ? "
        f"AND tmux_created_epoch = ?{scope_sql}",
        (socket, name, int(epoch), *scope_params),
    ).fetchone()
    return dict(row) if row is not None else None


def owned_instances(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET,
    host_key: str = LOCAL_HOST_KEY,
) -> Set[Tuple[str, int]]:
    if not sessions_table_ready(conn):
        return set()
    placeholders = ", ".join("?" for _ in SESSION_OWNED_ORIGINS)
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT tmux_name, tmux_created_epoch FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND origin IN ({placeholders}) "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, *SESSION_OWNED_ORIGINS),
    ).fetchall()
    return {(str(row[0]), int(row[1])) for row in rows}


def owned_names(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET
) -> Set[str]:
    return {name for name, _epoch in owned_instances(conn, socket=socket)}


def list_sessions(
    conn: sqlite3.Connection,
    *,
    lifecycle: Optional[str] = None,
    include_archived: bool = True,
    include_lineage: bool = False,
    include_automated: bool = True,
    include_companions: bool = False,
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    clauses: List[str] = []
    values: List[Any] = []
    if lifecycle is not None:
        clauses.append("s.lifecycle = ?")
        values.append(lifecycle)
    if not include_archived:
        clauses.append("s.archived_at IS NULL")
    if not include_lineage:
        clauses.append(
            "(s.parent_session_id IS NULL OR s.tmux_created_epoch IS NOT NULL)"
        )
    if not include_automated and column_exists(conn, "sessions", "kind"):
        clauses.append("COALESCE(s.kind, '') <> ?")
        values.append(SESSION_KIND_AUTOMATED)
    if not include_companions:
        companion = exclude_clause(conn, "s")
        if companion:
            clauses.append(companion[len(" AND "):])
    project_ready = _project_join_ready(conn)
    if project_ready:
        query = (
            "SELECT s.*, p.display_name AS project_name FROM sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id"
        )
    else:
        query = "SELECT s.*, NULL AS project_name FROM sessions s"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY s.id DESC"
    return [dict(row) for row in conn.execute(query, values).fetchall()]


def listable_sessions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    return list_sessions(
        conn, include_archived=False, include_automated=False
    )


def archive_session(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    now: Optional[str] = None,
) -> bool:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT archived_at FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    if row["archived_at"] is not None:
        return False

    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET archived_at = ?, updated_at = ? "
        "WHERE session_uuid = ? AND archived_at IS NULL",
        (stamp, stamp, session_uuid),
    )
    conn.commit()
    logger.info(
        "session_archived", session_uuid=session_uuid, archived_at=stamp
    )
    return True


def unarchive_session(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    now: Optional[str] = None,
) -> bool:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT archived_at FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    if row["archived_at"] is None:
        return False

    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET archived_at = NULL, updated_at = ? "
        "WHERE session_uuid = ? AND archived_at IS NOT NULL",
        (stamp, session_uuid),
    )
    conn.commit()
    logger.info("session_unarchived", session_uuid=session_uuid)
    return True


def notification_policy_rows(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        return []
    if not column_exists(
        conn, SESSIONS_TABLE, "notification_policy_generation"
    ):
        return []
    rows = conn.execute(
        "SELECT session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
        "notifications_muted, notification_policy_generation "
        "FROM sessions "
        "ORDER BY tmux_created_epoch ASC, id ASC"
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        epoch = row.get("tmux_created_epoch")
        try:
            epoch_value = int(epoch) if epoch is not None else None
        except (TypeError, ValueError):
            epoch_value = None
        out.append(
            {
                "session_uuid": row.get("session_uuid"),
                "tmux_socket": row.get("tmux_socket") or socket,
                "tmux_name": row.get("tmux_name"),
                "tmux_created_epoch": epoch_value,
                "muted": bool(row.get("notifications_muted")),
                "generation": int(
                    row.get("notification_policy_generation") or 0
                ),
            }
        )
    return out


def get_notification_policy(
    conn: sqlite3.Connection, session_uuid: str
) -> Dict[str, Any]:
    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT notifications_muted, notification_policy_generation "
        "FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    return {
        "muted": bool(row["notifications_muted"]),
        "generation": int(row["notification_policy_generation"] or 0),
    }


def set_notification_mute(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    muted: bool,
    expected_tmux_name: Optional[str] = None,
    expected_tmux_created_epoch: Optional[int] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT tmux_name, tmux_created_epoch, notifications_muted, "
        "notification_policy_generation FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)

    if expected_tmux_name is not None and expected_tmux_created_epoch is not None:
        stored_epoch = row["tmux_created_epoch"]
        try:
            stored_epoch = (
                int(stored_epoch) if stored_epoch is not None else None
            )
        except (TypeError, ValueError):
            stored_epoch = None
        if (
            row["tmux_name"] != expected_tmux_name
            or stored_epoch != int(expected_tmux_created_epoch)
        ):
            logger.warning(
                "session_notification_mute_instance_mismatch",
                session_uuid=session_uuid,
                expected_tmux_name=expected_tmux_name,
                expected_epoch=int(expected_tmux_created_epoch),
                stored_tmux_name=row["tmux_name"],
                stored_epoch=stored_epoch,
            )
            raise SessionInstanceMismatchError(session_uuid)

    current_muted = bool(row["notifications_muted"])
    current_generation = int(row["notification_policy_generation"] or 0)
    wanted = bool(muted)
    stored_name = row["tmux_name"]
    try:
        stored_epoch_out = (
            int(row["tmux_created_epoch"])
            if row["tmux_created_epoch"] is not None
            else None
        )
    except (TypeError, ValueError):
        stored_epoch_out = None

    if current_muted == wanted:
        return {
            "muted": current_muted,
            "generation": current_generation,
            "changed": False,
            "tmux_name": stored_name,
            "tmux_created_epoch": stored_epoch_out,
        }

    next_generation = current_generation + 1
    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET notifications_muted = ?, "
        "notification_policy_generation = ?, updated_at = ? "
        "WHERE session_uuid = ?",
        (1 if wanted else 0, next_generation, stamp, session_uuid),
    )
    conn.commit()
    logger.info(
        "session_notification_mute_set",
        session_uuid=session_uuid,
        muted=wanted,
        policy_generation=next_generation,
    )
    return {
        "muted": wanted,
        "generation": next_generation,
        "changed": True,
        "tmux_name": stored_name,
        "tmux_created_epoch": stored_epoch_out,
    }


def needs_attention(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    rows = conn.execute(
        "SELECT * FROM sessions "
        "WHERE (lifecycle = ? OR project_attribution = ?) "
        "AND parent_session_id IS NULL "
        "AND archived_at IS NULL"
        + exclude_clause(conn)
        + " ORDER BY id DESC",
        (SESSION_LIFECYCLE_UNKNOWN, SESSION_ATTRIBUTION_UNKNOWN),
    ).fetchall()
    return [dict(row) for row in rows]


def count_sessions(conn: sqlite3.Connection) -> int:
    if not sessions_table_ready(conn):
        return 0
    row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
    return int(row[0]) if row else 0


def is_owned_origin(origin: Optional[str]) -> bool:
    return origin in SESSION_OWNED_ORIGINS


def observed_origin_for(name: str, owned_tmux_names: Set[str]) -> str:
    from src.core.db_models import SESSION_ORIGIN_CREATED

    return (
        SESSION_ORIGIN_CREATED
        if name in owned_tmux_names
        else SESSION_ORIGIN_OBSERVED
    )


def identity_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn) or not name or epoch is None:
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT id, parent_session_id, agent_type, agent_family, "
        "agent_family_source FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
        (socket, *scope_params, name, epoch),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "parent_session_id": row["parent_session_id"],
        "agent_type": row["agent_type"],
        "agent_family": row["agent_family"],
        "agent_family_source": row["agent_family_source"],
    }


def identity_for_live_name(
    conn: Executor, *, socket: str, name: str, host_key: str = LOCAL_HOST_KEY
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn) or not name:
        return None
    project_ready = _project_join_ready(conn)
    if project_ready:
        scope_sql, scope_params = host_scope(conn, host_key, column="s.host_key")
        row = conn.execute(
            "SELECT s.id, s.parent_session_id, s.agent_type, s.agent_family, "
            "s.agent_family_source, s.claude_session_uuid, s.launch_record, s.project_id, "
            "p.display_name AS project_name "
            "FROM sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id "
            f"WHERE s.tmux_socket = ?{scope_sql} AND s.tmux_name = ? "
            "AND s.tmux_created_epoch IS NOT NULL "
            "ORDER BY s.tmux_created_epoch DESC, s.id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    else:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT id, parent_session_id, agent_type, agent_family, "
            "agent_family_source, claude_session_uuid, launch_record "
            "FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch IS NOT NULL "
            "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    if row is None:
        return None
    project_id = row["project_id"] if project_ready else None
    project_name = row["project_name"] if project_ready else None
    return {
        "id": int(row["id"]),
        "parent_session_id": row["parent_session_id"],
        "agent_type": row["agent_type"],
        "agent_family": row["agent_family"],
        "agent_family_source": row["agent_family_source"],
        "claude_session_uuid": row["claude_session_uuid"] or None,
        "launch_record": row["launch_record"],
        "project_id": int(project_id) if project_id is not None else None,
        "project_name": project_name,
    }
