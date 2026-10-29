
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.crate_import import idmap, share_in
from src.core.crate_import import rows_write as rw
from src.core.crate_import.analysis import Analysis
from src.core.crate_import.model import ACTION_CREATE, W_FORK_PARENT_NOT_CARRIED
from src.core.project_colors.legacy_keys import stored_hex
from src.core.project_writes import insert_project_row
from src.core.transcript_import_plan import IMPORTED_ROW_CONSTANTS

logger = structlog.get_logger()

COMPANIES, PROJECTS, SESSIONS, SESSION_UUIDS = idmap.COMPANIES, idmap.PROJECTS, idmap.SESSIONS, idmap.SESSION_UUIDS
SESSION_RESET = ("activity_state", "activity_state_at", "last_seen_running_at", "adopted_at", "user_declined_at", "unread_auto",
                 "unread_manual", "tmux_socket", "lifecycle_checked_at")
PROJECT_EXTRAS = ("color", "short_description")


def write_companies(ctx: rw.WriteCtx, rows: List[Dict[str, Any]]) -> Dict[int, Tuple[Optional[int], Optional[int]]]:
    counts, deferred = ctx.table_counts(COMPANIES), {}
    for source in rows:
        row = dict(source)
        old_id = row.pop("id", None)
        parent_old, hq_old = row.pop("parent_id", None), row.pop("hq_project_id", None)
        here = ctx.conn.execute("SELECT id FROM companies WHERE uid = ?", (row.get("uid"),)).fetchone() if row.get("uid") else None
        here = here or ctx.conn.execute("SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (row.get("name"),)).fetchone()
        if here is not None:
            ctx.idmap.put(COMPANIES, old_id, here["id"])
            counts.present += 1
            continue
        try:
            inserted, rowid = rw.insert_row(ctx, "companies", rw.own_columns(ctx, "companies", row), ignore=False)
        except sqlite3.IntegrityError:
            counts.skip("refused_by_unique_rule")
            continue
        counts.inserted += 1
        ctx.idmap.put(COMPANIES, old_id, rowid)
        ctx.created.setdefault(COMPANIES, []).append(rowid)
        deferred[int(rowid)] = (parent_old, hq_old)
    return deferred


def finish_companies(ctx: rw.WriteCtx, deferred: Dict[int, Tuple[Optional[int], Optional[int]]]) -> None:
    for local_id, (parent_old, hq_old) in deferred.items():
        parent = ctx.idmap.get(COMPANIES, parent_old) if parent_old is not None else None
        hq = ctx.idmap.get(PROJECTS, hq_old) if hq_old is not None else None
        if parent_old is not None and parent is None or hq_old is not None and hq is None:
            from src.core.crate_import.model import W_DANGLING_REF

            ctx.col.warn(W_DANGLING_REF, f"{COMPANIES}.parent_or_hq")
        if parent is not None or hq is not None:
            ctx.conn.execute("UPDATE companies SET parent_id = COALESCE(?, parent_id), hq_project_id = COALESCE(?, hq_project_id) WHERE id = ?",
                             (parent, hq, local_id))


def write_project(ctx: rw.WriteCtx, a: Analysis, now: Optional[str] = None) -> Dict[str, Any]:
    decision, counts = a.decision, ctx.table_counts(PROJECTS)
    crate_row = (a.rows.project_rows[0] if a.rows and a.rows.project_rows else {})
    old_id = crate_row.get("id")
    if decision.action != ACTION_CREATE:
        counts.present += 1
        if old_id is not None:
            ctx.idmap.put(PROJECTS, old_id, decision.project_id)
        return {"project_id": decision.project_id, "created": False, "cleared_tombstone": None, "adopted": []}
    row, cleared, adopted = insert_project_row(
        ctx.conn, root=str(decision.root_to), raw_path=str(decision.root_to), name=decision.name, uid=decision.uid, source="user",
        skip_session_ids=a.live.live_row_ids, description=crate_row.get("description"), agent_type=crate_row.get("default_agent_type"),
        now=now)
    extras = {c: crate_row[c] for c in PROJECT_EXTRAS if crate_row.get(c) is not None}
    if "color" in extras:
        extras["color"] = stored_hex(extras["color"])
        if extras["color"] is None:
            del extras["color"]
    company = ctx.idmap.get(COMPANIES, crate_row["company_id"]) if crate_row.get("company_id") is not None else None
    if company is not None:
        extras["company_id"] = company
    if extras:
        ctx.conn.execute(f"UPDATE projects SET {', '.join(f'{c} = ?' for c in extras)} WHERE id = ?", (*extras.values(), row["id"]))
    counts.inserted += 1
    if old_id is not None:
        ctx.idmap.put(PROJECTS, old_id, row["id"])
    ctx.created.setdefault(PROJECTS, []).append(row["id"])
    return {"project_id": row["id"], "created": True, "cleared_tombstone": cleared, "adopted": adopted}


def write_sessions(ctx: rw.WriteCtx, a: Analysis, project_id: int) -> None:
    if share_in.is_share(a.manifest):
        share_in.write_sessions(ctx, a.manifest, [p.record for p in a.placements], project_id, a.decision.root_to)
        return
    counts, parents = ctx.table_counts(SESSIONS), []
    rows = (a.rows.sanitized.get(SESSIONS, []) if a.rows else [])
    project_old = (a.rows.project_rows[0].get("id") if a.rows and a.rows.project_rows else None)  # own project
    for source in rows:
        row = dict(source)
        old_id, parent_old = row.pop("id", None), row.pop("parent_session_id", None)
        here = ctx.conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (row["session_uuid"],)).fetchone()
        if here is not None:
            if old_id is not None:
                ctx.idmap.put(SESSIONS, old_id, here["id"])
            counts.present += 1
            continue
        for column in SESSION_RESET:
            row.pop(column, None)
        # own project
        own_project = row.get("project_id") is None or project_old is None or row["project_id"] == project_old
        mapped_project = None if own_project else ctx.idmap.get(PROJECTS, row["project_id"])
        row.update(IMPORTED_ROW_CONSTANTS)
        row["project_id"] = mapped_project if mapped_project is not None else project_id
        if source.get("claude_session_uuid_source"):
            row["claude_session_uuid_source"] = source["claude_session_uuid_source"]
        try:
            inserted, rowid = rw.insert_row(ctx, "sessions", rw.own_columns(ctx, "sessions", row), ignore=False)
        except sqlite3.IntegrityError as exc:
            logger.warning("crate_import_session_refused", error=str(exc)[:120])
            counts.skip("refused_by_unique_rule")
            continue
        counts.inserted += 1
        if old_id is not None:
            ctx.idmap.put(SESSIONS, old_id, rowid)
        ctx.created.setdefault(SESSIONS, []).append(rowid)
        if parent_old is not None:
            parents.append((rowid, parent_old))
    for rowid, parent_old in parents:
        parent = ctx.idmap.get(SESSIONS, parent_old)
        if parent is None:
            ctx.col.warn(W_FORK_PARENT_NOT_CARRIED, str(rowid))
        else:
            ctx.conn.execute("UPDATE sessions SET parent_session_id = ? WHERE id = ?", (parent, rowid))
