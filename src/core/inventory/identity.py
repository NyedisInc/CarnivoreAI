
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from src.core.db import table_exists
from src.core.inventory.model import ProjectIdentity, ProjectNotFound, SessionIdentity, SessionNotFound

SAFE_CONVERSATION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")

def safe_conversation(conversation: Optional[str]) -> Optional[str]:
    return conversation if conversation and SAFE_CONVERSATION.match(conversation) else None


_SESSION_COLUMNS = ("id", "session_uuid", "tmux_name", "tmux_created_epoch", "title", "claude_session_uuid",
                    "agent_family", "working_dir", "host_key", "lifecycle", "archived_at", "legacy_session_id",
                    "project_id")
_PROJECT_COLUMNS = ("id", "uid", "display_name", "root", "raw_path", "company_id", "archived_at")


def load_identity(conn: sqlite3.Connection, session_uuid: str) -> SessionIdentity:
    row = conn.execute(f"SELECT {', '.join(_SESSION_COLUMNS)} FROM sessions WHERE session_uuid = ?",
                       (session_uuid,)).fetchone()
    if row is None:
        raise SessionNotFound(session_uuid)
    epoch = row["tmux_created_epoch"]
    return SessionIdentity(
        row_id=int(row["id"]), session_uuid=str(row["session_uuid"]), tmux_name=row["tmux_name"],
        tmux_epoch=int(epoch) if epoch is not None else None, title=row["title"],
        conversation=row["claude_session_uuid"], agent_family=row["agent_family"], working_dir=row["working_dir"],
        host_key=row["host_key"], lifecycle=row["lifecycle"], archived_at=row["archived_at"],
        app_id=row["legacy_session_id"], project_id=row["project_id"],
    )


def load_project(conn: sqlite3.Connection, project_id: int) -> ProjectIdentity:
    row = conn.execute(f"SELECT {', '.join(_PROJECT_COLUMNS)} FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFound(str(project_id))
    return ProjectIdentity(project_id=int(row["id"]), uid=row["uid"], name=row["display_name"], root=str(row["root"]),
                           raw_path=row["raw_path"], company_id=row["company_id"], archived_at=row["archived_at"])


def project_session_uuids(conn: sqlite3.Connection, project_id: int) -> List[str]:
    return [str(r[0]) for r in conn.execute("SELECT session_uuid FROM sessions WHERE project_id = ? ORDER BY id",
                                            (project_id,))]


def related_conversations(conn: sqlite3.Connection, ident: SessionIdentity) -> List[str]:
    found: List[str] = []
    for table in ("conversation_index", "conversation_milestones"):
        if not table_exists(conn, table):
            continue
        for (conv,) in conn.execute(f"SELECT DISTINCT conversation_id FROM {table} WHERE session_uuid = ? "
                                    "AND conversation_id IS NOT NULL ORDER BY conversation_id", (ident.session_uuid,)):
            if conv and conv != ident.conversation and conv not in found:
                found.append(str(conv))
    return found


def shared_with(conn: sqlite3.Connection, ident: SessionIdentity) -> List[Dict[str, Any]]:
    if not ident.conversation:
        return []
    name = "COALESCE(NULLIF(s.title, ''), s.tmux_name, s.session_uuid)"
    sql = (f"SELECT s.session_uuid, {name} AS name FROM sessions s WHERE s.id != ? AND "
           "(s.claude_session_uuid = ?")
    params: List[Any] = [ident.row_id, ident.conversation]
    if table_exists(conn, "conversation_index"):
        sql += " OR s.session_uuid IN (SELECT session_uuid FROM conversation_index WHERE conversation_id = ?)"
        params.append(ident.conversation)
    rows = conn.execute(sql + ") ORDER BY s.id", params).fetchall()
    return [{"session_uuid": r["session_uuid"], "name": r["name"]} for r in rows]


def other_rows_named(conn: sqlite3.Connection, ident: SessionIdentity) -> int:
    if not ident.tmux_name:
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM sessions WHERE tmux_name = ? AND id != ?",
                            (ident.tmux_name, ident.row_id)).fetchone()[0])


def project_of(conn: sqlite3.Connection, ident: SessionIdentity) -> Optional[ProjectIdentity]:
    if ident.project_id is None:
        return None
    try:
        return load_project(conn, int(ident.project_id))
    except ProjectNotFound:
        return None
