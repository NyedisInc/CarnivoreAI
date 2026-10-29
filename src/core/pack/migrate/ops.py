
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, List, Mapping, Optional

from src.core.db import transaction
from src.core.mcp import family_signals
from src.core.trail_entry import utc_now

STEPS = ("prepare", "code", "rows", "transcripts", "verify", "flip")
LIVE_STEPS = ("wait", "sleep", "stop_shells")
INTERRUPT_STEP, CONTINUE_STEP = "interrupt", "continue"


def steps_for(detail: Mapping[str, Any]) -> List[str]:
    live, stop = bool(detail.get("live")), bool(detail.get("stop_running"))
    return [*((INTERRUPT_STEP,) if live and stop else ()), *(LIVE_STEPS if live else ()), *STEPS, *(("wake",) if live else ()), *((CONTINUE_STEP,) if live and stop else ())]


def new_id() -> str:
    return uuid.uuid4().hex


def _notify(op_id: str) -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    family_signals.invalidate("pack")
    resource_push.notify(topics.keyed(topics.PACK_OPS, op_id))
    resource_push.notify(topics.PACK_OPS)


def create(conn: sqlite3.Connection, *, op_id: str, kind: str, role: str, subject_uid: str, source_install_id: str,
           target_install_id: str, fingerprint: Optional[str] = None, parent_id: Optional[str] = None, state: str = "applying",
           step: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM pack_migrations WHERE id = ? AND role = ?", (op_id, role))
        conn.execute(
            "INSERT INTO pack_migrations (id, kind, role, parent_id, subject_uid, source_install_id, target_install_id, plan_fingerprint, "
            "state, step, detail_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (op_id, kind, role, parent_id, subject_uid, source_install_id, target_install_id, fingerprint, state, step,
             json.dumps(detail or {}), utc_now()))
    _notify(op_id)


def update(conn: sqlite3.Connection, op_id: str, role: str, *, state: Optional[str] = None, step: Optional[str] = None,
           error_code: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None) -> None:
    with transaction(conn):
        row = conn.execute("SELECT detail_json FROM pack_migrations WHERE id = ? AND role = ?", (op_id, role)).fetchone()
        if row is None:
            return
        merged = {**json.loads(row[0] or "{}"), **(detail or {})}
        done = state in ("flipped", "failed", "moved_back")
        conn.execute(
            "UPDATE pack_migrations SET state = COALESCE(?, state), step = COALESCE(?, step), error_code = COALESCE(?, error_code), "
            "detail_json = ?, finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE id = ? AND role = ?",
            (state, step, error_code, json.dumps(merged), 1 if done else 0, utc_now(), op_id, role))
    _notify(op_id)


def read(conn: sqlite3.Connection, op_id: str, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM pack_migrations WHERE id = ? ORDER BY role = 'source' DESC", (op_id,)).fetchall()
    for row in rows:
        if role is None or row["role"] == role:
            out = dict(row)
            out["detail"] = json.loads(out.pop("detail_json") or "{}")
            out.pop("manifest_json", None)
            return out
    return None


def view(conn: sqlite3.Connection, op_id: str) -> Optional[Dict[str, Any]]:
    op = read(conn, op_id)
    if op is None:
        return None
    children: List[Dict[str, Any]] = [
        {k: c[k] for k in ("id", "subject_uid", "state", "step", "error_code")}
        for c in (dict(r) for r in conn.execute("SELECT * FROM pack_migrations WHERE parent_id = ? AND role = ? ORDER BY started_at", (op_id, op["role"])))]
    for child in children:
        detail = (read(conn, child["id"]) or {}).get("detail", {})
        child["name"] = detail.get("name")
    op["children"] = children
    op["steps"] = steps_for(op["detail"])
    return op
