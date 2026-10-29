
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.db import table_exists as _table_exists
from src.core.inventory import registry
from src.core.inventory.identity import safe_conversation
from src.core.inventory.claim_rows import annotate, trace_claims
from src.core.inventory.model import DELETE, KEEP, KIND_ROWS, MAIN_STORE, Artifact, SessionIdentity
from src.core.inventory.scope import Scope, session_scope

STORE = MAIN_STORE


def _path_match(column: str, conversation: str) -> Tuple[str, List[str]]:
    return (f"({column} LIKE ? OR {column} LIKE ? OR {column} LIKE ?)",
            [f"%/{conversation}.jsonl", f"%-{conversation}.jsonl", f"%/{conversation}/%"])


def _rows(conn: sqlite3.Connection, table: str, where: str, params: Sequence[Any], *, action: str = DELETE,
          reason: str = "") -> Optional[Artifact]:
    if not _table_exists(conn, table):
        return None
    count = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", tuple(params)).fetchone()[0])
    if not count:
        return None
    return Artifact(store=STORE, kind=KIND_ROWS, what=table, count=count, action=action, reason=reason,
                    locator={"table": table, "where": where, "params": list(params), "db": None})


def _archive_ids(conn: sqlite3.Connection, ident: SessionIdentity) -> List[int]:
    if not _table_exists(conn, "transcript_archives"):
        return []
    where, params = ["root_session_id = ?"], [ident.row_id]
    conversation = safe_conversation(ident.conversation)
    if conversation:
        match, more = _path_match("source_path", conversation)
        where += ["claude_session_uuid = ?", match]
        params += [conversation, *more]
    sql = f"SELECT id FROM transcript_archives WHERE {' OR '.join(where)} ORDER BY id"
    return [int(r[0]) for r in conn.execute(sql, params)]


def _in(ids: Sequence[int]) -> str:
    return "(" + ", ".join("?" for _ in ids) + ")"


def _corpus_transcripts(conn: sqlite3.Connection, conversation: str, archive_ids: Sequence[int]) -> List[int]:
    if not _table_exists(conn, "message_transcripts"):
        return []
    tails: List[str] = []
    if archive_ids:
        tails = [f"::{r[0]}" for r in conn.execute(
            f"SELECT source_path FROM transcript_archives WHERE id IN {_in(archive_ids)}", list(archive_ids))]
    found = {int(r[0]) for r in conn.execute(
        "SELECT id FROM message_transcripts WHERE session_ref = ? AND session_ref_scheme = 'uuid'",
        (conversation,))}
    for tail in tails:
        found.update(int(r[0]) for r in conn.execute(
            "SELECT id FROM message_transcripts WHERE substr(source_ref, -?) = ?", (len(tail), tail)))
    return sorted(found)


EXCLUSIVE_BODIES_SQL = (
    "SELECT DISTINCT a.body_id FROM message_appearances a WHERE a.transcript_id IN {ids} AND a.body_id IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM message_appearances b WHERE b.body_id = a.body_id AND b.transcript_id NOT IN {ids})"
)


def exclusive_bodies(conn: sqlite3.Connection, transcript_ids: Sequence[int]) -> List[int]:
    if not transcript_ids or not _table_exists(conn, "message_appearances"):
        return []
    sql = EXCLUSIVE_BODIES_SQL.format(ids=_in(transcript_ids))
    return sorted(int(r[0]) for r in conn.execute(sql, [*transcript_ids, *transcript_ids]))


def trace(conn: sqlite3.Connection, ident: SessionIdentity, shared: List[Dict[str, Any]],
          other_named: int, scope: Optional[Scope] = None) -> Tuple[List[Artifact], List[str]]:
    arts: List[Optional[Artifact]] = []
    blockers: List[str] = []
    conv = safe_conversation(ident.conversation)
    conv_action, conv_reason = DELETE, ""
    if shared:
        conv_action = KEEP
        conv_reason = "the conversation is shared with session " + ", ".join(s["name"] for s in shared)

    def conv_rows(table: str, key: str = "conversation_id") -> Optional[Artifact]:
        return _rows(conn, table, f"{key} = ? AND COALESCE(session_uuid, '') != ?", [conv, ident.session_uuid],
                     action=conv_action, reason=conv_reason) if conv else None

    arts.append(_rows(conn, "session_notes", "session_uuid = ?", [ident.session_uuid]))
    arts.append(_rows(conn, "session_group_membership", "session_uuid = ?", [ident.session_uuid]))
    if ident.tmux_name:
        arts.append(_rows(conn, "session_group_members", "tmux_name = ?", [ident.tmux_name],
                          action=KEEP if other_named else DELETE,
                          reason="keyed by tmux name, which another session row also carries" if other_named else ""))
    arts.append(_rows(conn, "layout_broadcast_off", "session_row_id = ?", [ident.row_id]))
    arts.append(_rows(conn, "layout_members", "session_row_id = ?", [ident.row_id]))
    arts.append(_rows(conn, "conversation_milestones", "session_uuid = ?", [ident.session_uuid]))
    arts.append(conv_rows("conversation_milestones"))
    arts.append(_rows(conn, "conversation_index", "session_uuid = ?", [ident.session_uuid]))
    arts.append(conv_rows("conversation_index"))
    jobs_where = "session_uuid = ?" + (" OR conversation_id = ?" if conv and not shared else "")
    jobs_params: List[Any] = [ident.session_uuid] + ([conv] if conv and not shared else [])
    if _table_exists(conn, "pipeline_jobs"):
        arts.append(_rows(conn, "pipeline_stage_runs", f"job_id IN (SELECT id FROM pipeline_jobs WHERE {jobs_where})",
                          jobs_params))
        arts.append(_rows(conn, "pipeline_jobs", jobs_where, jobs_params))
        if conv and shared:
            arts.append(conv_rows("pipeline_jobs"))
    if conv:
        match, more = _path_match("path", conv)
        arts.append(_rows(conn, "transcript_files", f"conversation_id = ? OR {match}", [conv, *more],
                          action=conv_action, reason=conv_reason))
    archive_ids = _archive_ids(conn, ident)
    if archive_ids:
        rooted_here = [int(r[0]) for r in conn.execute(
            f"SELECT id FROM transcript_archives WHERE id IN {_in(archive_ids)} AND root_session_id = ?",
            [*archive_ids, ident.row_id])]
        if shared and rooted_here:
            blockers.append(f"{len(rooted_here)} archived transcript(s) of the shared conversation are rooted on "
                            "this session row; re-root them before purging")
        outside = conn.execute(
            f"SELECT COUNT(*) FROM transcript_archives WHERE id NOT IN {_in(archive_ids)} AND "
            f"(parent_archive_id IN {_in(archive_ids)} OR superseded_by_archive_id IN {_in(archive_ids)})",
            [*archive_ids] * 3).fetchone()[0]
        if outside and not shared:
            blockers.append(f"{outside} archived transcript(s) of another conversation point at this one's archive")
        ids = list(archive_ids)
        arts.append(_rows(conn, "transcript_root_decisions", f"archive_id IN {_in(ids)}", ids,
                          action=conv_action, reason=conv_reason))
        arts.append(_rows(conn, "transcript_records", f"archive_id IN {_in(ids)}", ids,
                          action=conv_action, reason=conv_reason))
        corpus = _corpus_transcripts(conn, conv, ids) if conv else []
        if corpus:
            arts.append(_rows(conn, "message_appearances", f"transcript_id IN {_in(corpus)}", corpus,
                              action=conv_action, reason=conv_reason))
            bodies = exclusive_bodies(conn, corpus)
            arts.append(_rows(conn, "message_transcripts", f"id IN {_in(corpus)}", corpus,
                              action=conv_action, reason=conv_reason))
            if bodies:
                art = _rows(conn, "message_bodies", f"id IN {_in(bodies)}", bodies, action=conv_action,
                            reason=conv_reason)
                if art is not None:
                    art.what = "message_bodies (only those no other conversation shows)"
                    art.op = {"fn": "exclusive_bodies", "transcripts": corpus}
                arts.append(art)
        arts.append(_rows(conn, "transcript_archives", f"id IN {_in(ids)}", ids, action=conv_action,
                          reason=conv_reason))
    arts.append(_rows(conn, "sessions", "id = ?", [ident.row_id]))
    found = [a for a in arts if a is not None]
    keys = scope if scope is not None else session_scope(conn, ident)
    annotate(registry.book(), found, keys)
    return found + trace_claims(registry.book(), keys, STORE, conn), blockers


def delete(conn: sqlite3.Connection, art: Artifact, *, bodies_op: Optional[Dict[str, Any]] = None) -> int:
    if bodies_op is not None:
        ids = bodies_op["ids"]
        return conn.execute(f"DELETE FROM message_bodies WHERE id IN {_in(ids)}", ids).rowcount if ids else 0
    loc = art.locator
    return conn.execute(f"DELETE FROM {loc['table']} WHERE {loc['where']}", loc["params"]).rowcount
