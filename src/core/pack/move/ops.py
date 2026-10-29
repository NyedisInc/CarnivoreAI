
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, Mapping, Optional

from src.core.db import transaction
from src.core.pack import progress
from src.core.trail_entry import utc_now

STEPS_BY_MODE = {"move": ("project", "check", "interrupt", "wait", "code", "sleep", "stop_shells", "carry", "wake", "forward", "continue"),
                 "copy": ("project", "check", "wait", "code", "carry", "wake"),
                 "fresh": ("project", "check", "code", "wake")}


def new_id() -> str:
    return uuid.uuid4().hex


def _notify(op_id: str) -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    resource_push.notify(topics.keyed(topics.PACK_OPS, op_id))
    resource_push.notify(topics.PACK_OPS)


def create(conn: sqlite3.Connection, *, op_id: str, role: str, session_uuid: str, claude_session_uuid: Optional[str],
           source_install_id: str, target_install_id: str, state: str = "waiting", step: str = "check",
           detail: Optional[Mapping[str, Any]] = None) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM pack_session_moves WHERE id = ? AND role = ?", (op_id, role))
        conn.execute(
            "INSERT INTO pack_session_moves (id, role, session_uuid, claude_session_uuid, source_install_id, target_install_id, state, step, "
            "detail_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (op_id, role, session_uuid, claude_session_uuid, source_install_id, target_install_id, state, step, json.dumps(detail or {}), utc_now()))
    _notify(op_id)


def update(conn: sqlite3.Connection, op_id: str, role: str, *, state: Optional[str] = None, step: Optional[str] = None,
           error_code: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None) -> None:
    with transaction(conn):
        row = conn.execute("SELECT detail_json FROM pack_session_moves WHERE id = ? AND role = ?", (op_id, role)).fetchone()
        if row is None:
            return
        merged = {**json.loads(row[0] or "{}"), **(detail or {})}
        done = state in ("moved", "failed")
        conn.execute(
            "UPDATE pack_session_moves SET state = COALESCE(?, state), step = COALESCE(?, step), error_code = COALESCE(?, error_code), "
            "detail_json = ?, finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE id = ? AND role = ?",
            (state, step, error_code, json.dumps(merged), 1 if done else 0, utc_now(), op_id, role))
    progress.on_update(op_id, role, state=state, step=step, error_code=error_code, detail=detail)
    _notify(op_id)


def view(conn: sqlite3.Connection, op_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM pack_session_moves WHERE id = ? ORDER BY role = 'source' DESC", (op_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["detail"] = json.loads(out.pop("detail_json") or "{}")
    out.update(kind="session", steps=list(STEPS_BY_MODE.get(out["detail"].get("mode", "move"), STEPS_BY_MODE["move"])), children=[])
    return out


def forward_for(conn: sqlite3.Connection, session_uuid: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM pack_session_moves WHERE session_uuid = ? AND role = 'source' AND state = 'moved' "
                       "AND COALESCE(json_extract(detail_json, '$.mode'), 'move') = 'move' ORDER BY started_at DESC LIMIT 1",
                       (session_uuid,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["detail"] = json.loads(out.pop("detail_json") or "{}")
    return out
