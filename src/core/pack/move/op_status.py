
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.core.pack import progress
from src.core.pack.move import inflight
from src.core.pack.identity import home
from src.core.pack.migrate import ops as migrate_ops
from src.core.pack.move import ops as move_ops

RECENT_SECONDS = 900
logger = structlog.get_logger()
MOVE_DONE = ("moved", "failed")
MIGRATE_DONE = ("flipped", "failed", "moved_back")


def _stamp(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _detail(raw: Optional[str]) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def status_of(conn: sqlite3.Connection, row: sqlite3.Row, *, session: bool) -> Dict[str, Any]:
    data, detail = dict(row), _detail(row["detail_json"])
    done_states = MOVE_DONE if session else MIGRATE_DONE
    running = data["state"] not in done_states
    source = data["role"] == "source"
    other = data["target_install_id"] if source else data["source_install_id"]
    in_process = inflight.running(data["id"])
    blocked = inflight.blocked_reason(data["id"]) if running else None
    error = detail.get("error")
    return {
        "id": data["id"],
        "kind": "session" if session else data["kind"],
        "direction": "out" if source else "in",
        "name": detail.get("name"),
        "machine": detail.get("machine") or home.machine_label(conn, other),
        "mode": detail.get("mode"),
        "state": data["state"],
        "step": data["step"],
        "steps": list(move_ops.STEPS_BY_MODE.get(detail.get("mode") or "move", move_ops.STEPS_BY_MODE["move"])) if session else migrate_ops.steps_for(detail),
        "error_code": data["error_code"],
        "error": error if isinstance(error, str) else None,
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
        "session_uuid": data["session_uuid"] if session else None,
        "target_session_uuid": detail.get("target_session_uuid"),
        "claude_session_uuid": data["claude_session_uuid"] if session else None,
        "working_dir": detail.get("working_dir"),
        "wait_until": detail.get("wait_until") if data["step"] == "wait" else None,
        "waiting_on": detail.get("waiting_on") or None if data["step"] == "wait" and running else None,
        "agents": detail.get("agents") if data["step"] in ("interrupt", "wait", "wake", "continue") else None,
        "woken": detail.get("woken"),
        "wake_failed": detail.get("wake_failed"),
        "told": detail.get("told"),
        "continue_failed": detail.get("continue_failed"),
        "shells": detail.get("shells") if data["step"] == "stop_shells" else None,
        "running": running,
        "interrupted": running and source and not in_process,
        "cancellable": running and source and in_process and blocked is None,
        "cancel_blocked": blocked,
        "progress": progress.view(data["id"]),
    }


def recent(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    since = _stamp(RECENT_SECONDS)
    moves = conn.execute("SELECT * FROM pack_session_moves WHERE role = 'source' AND (finished_at IS NULL OR finished_at >= ?)", (since,)).fetchall()
    migrations = conn.execute("SELECT * FROM pack_migrations WHERE parent_id IS NULL AND state != 'planned' AND (finished_at IS NULL OR finished_at >= ?)", (since,)).fetchall()
    found = [status_of(conn, r, session=True) for r in moves] + [status_of(conn, r, session=False) for r in migrations]
    return sorted(found, key=lambda o: o["started_at"] or "", reverse=True)


def one(conn: sqlite3.Connection, op_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM pack_session_moves WHERE id = ? ORDER BY role = 'source' DESC", (op_id,)).fetchone()
    if row is not None:
        return status_of(conn, row, session=True)
    row = conn.execute("SELECT * FROM pack_migrations WHERE id = ? ORDER BY role = 'source' DESC", (op_id,)).fetchone()
    return status_of(conn, row, session=False) if row is not None else None


def mark_interrupted(conn: sqlite3.Connection, op_id: str) -> bool:
    status = one(conn, op_id)
    if status is None or not status["interrupted"]:
        return False
    if status["kind"] == "session":
        move_ops.update(conn, op_id, "source", state="failed", error_code="interrupted")
    else:
        migrate_ops.update(conn, op_id, "source", state="failed", error_code="interrupted")
    return True



def close_orphans(conn: sqlite3.Connection) -> int:
    closed = 0
    for row in conn.execute("SELECT id FROM pack_session_moves WHERE role = 'source' AND state NOT IN ('moved', 'failed')").fetchall():
        move_ops.update(conn, row[0], "source", state="failed", error_code="interrupted")
        closed += 1
    for row in conn.execute("SELECT id FROM pack_migrations WHERE role = 'source' AND state IN ('applying', 'verifying')").fetchall():
        migrate_ops.update(conn, row[0], "source", state="failed", error_code="interrupted")
        closed += 1
    return closed


def close_orphans_at_boot(state_dir: Any) -> None:
    from contextlib import closing
    from src.core.db import connect, db_path_for

    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            closed = close_orphans(conn)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("pack_ops_orphan_sweep_failed", error=type(exc).__name__)
        return
    if closed:
        logger.info("pack_ops_orphans_closed", count=closed)
