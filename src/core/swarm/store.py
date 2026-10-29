
from __future__ import annotations

import os
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.db import transaction
from src.core.swarm import push
from src.core.swarm.slugs import is_valid_slug
from src.core.trail_entry import utc_now

_UPDATABLE = frozenset(
    {
        "parent_id", "display_name", "persona", "job", "naming_family", "naming_state", "repo_dir", "memory_scope",
        "project_id", "company_id", "harness", "launch_profile", "model", "effort", "effort_reason", "goal",
        "task_type", "origin_message_ref", "thread_key", "turn_authority", "turn_opened_at", "color_slot",
        "color_chosen", "specialty", "former_names", "shape", "tile_bg", "host_key",
    }
)
_WAKE_UPDATABLE = frozenset({"conversation_uuid", "tmux_name", "tmux_epoch"})


def _changed(agent_id: int) -> None:
    push.notify_roster()
    push.notify_agent(agent_id)


class AgentNotFound(LookupError):
    pass


def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def create_agent(
    conn: sqlite3.Connection,
    *,
    slug: str,
    rank: str,
    job: str,
    display_name: str,
    repo_dir: str,
    effort: str,
    parent_id: Optional[int] = None,
    memory_scope: Optional[str] = None,
    thread_key: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid slug {slug!r}")
    unknown = set(extra) - _UPDATABLE - {"character_seed", "color_slot", "session_row_id"}
    if unknown:
        raise ValueError(f"unknown columns {sorted(unknown)}")
    now = utc_now()
    fields: Dict[str, Any] = {
        "slug": slug, "rank": rank, "parent_id": parent_id, "job": job, "display_name": display_name,
        "repo_dir": os.path.realpath(repo_dir), "effort": effort,
        "memory_scope": memory_scope or ("local" if rank == "task" else "project"),
        "character_seed": random.SystemRandom().randrange(1, 2**31), "color_slot": random.randint(1, 8),
        "state": "asleep", "created_at": now, "updated_at": now,
    }
    fields.update(extra)
    if thread_key is None and rank == "alpha":
        thread_key = "all"
    elif thread_key is None and rank == "project" and fields.get("project_id") is not None:
        thread_key = str(fields["project_id"])
    pending = thread_key is None
    fields["thread_key"] = thread_key or f"pending:{uuid.uuid4().hex}"
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with transaction(conn):
        agent_id = conn.execute(f"INSERT INTO swarm_agents ({cols}) VALUES ({marks})", tuple(fields.values())).lastrowid
        if pending:
            conn.execute("UPDATE swarm_agents SET thread_key = ? WHERE id = ?", (f"agent:{agent_id}", agent_id))
    _changed(agent_id)
    return get_agent(conn, agent_id) or {}


def get_agent(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_agents WHERE id = ?", (agent_id,)).fetchone())


def get_agent_by_session_row(conn: sqlite3.Connection, session_row_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_agents WHERE session_row_id = ?", (session_row_id,)).fetchone())


def get_agent_by_thread_key(conn: sqlite3.Connection, thread_key: str) -> Optional[Dict[str, Any]]:
    return _row(
        conn.execute(
            "SELECT * FROM swarm_agents WHERE thread_key = ? AND torn_down_at IS NULL", (thread_key,)
        ).fetchone()
    )


def list_agents(
    conn: sqlite3.Connection, *, parent_id: Optional[int] = None, include_torn_down: bool = False
) -> List[Dict[str, Any]]:
    where, args = [], []
    if not include_torn_down:
        where.append("torn_down_at IS NULL")
    if parent_id is not None:
        where.append("parent_id = ?")
        args.append(parent_id)
    sql = "SELECT * FROM swarm_agents" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def update_agent(conn: sqlite3.Connection, agent_id: int, **fields: Any) -> Dict[str, Any]:
    unknown = set(fields) - _UPDATABLE
    if unknown or not fields:
        raise ValueError(f"cannot update {sorted(unknown) or 'nothing'}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    with transaction(conn):
        cur = conn.execute(
            f"UPDATE swarm_agents SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), utc_now(), agent_id)
        )
        if cur.rowcount == 0:
            raise AgentNotFound(agent_id)
    _changed(agent_id)
    return get_agent(conn, agent_id) or {}


def cas_state(conn: sqlite3.Connection, agent_id: int, expected: str, new: str) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE swarm_agents SET state = ?, updated_at = ? WHERE id = ? AND state = ?",
            (new, utc_now(), agent_id, expected),
        )
    if cur.rowcount == 1:
        _changed(agent_id)
    return cur.rowcount == 1


def set_session_row(conn: sqlite3.Connection, agent_id: int, session_row_id: int) -> None:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE swarm_agents SET session_row_id = ?, updated_at = ? WHERE id = ? AND session_row_id IS NULL",
            (session_row_id, utc_now(), agent_id),
        )
        if cur.rowcount == 0:
            raise AgentNotFound(agent_id)
    _changed(agent_id)


def rebind_session_row(conn: sqlite3.Connection, agent_id: int, session_row_id: int) -> None:
    """Point an ASLEEP agent at another sessions row (re-pointing a project agent to a promoted session, ``project_promote.py``).

    Inputs: conn; agent_id; session_row_id (a row no other agent holds: the UNIQUE index refuses it).
    Raises: AgentNotFound (unknown, torn down, or not asleep: a body must not be switched under a running wake), sqlite3.IntegrityError.
    """
    with transaction(conn):
        cur = conn.execute("UPDATE swarm_agents SET session_row_id = ?, updated_at = ? WHERE id = ? AND state = 'asleep' AND torn_down_at IS NULL",
                           (session_row_id, utc_now(), agent_id))
        if cur.rowcount == 0:
            raise AgentNotFound(agent_id)
    _changed(agent_id)


def open_wake(
    conn: sqlite3.Connection, agent_id: int, *, reason: str, mode: str, authority: str
) -> Optional[int]:
    """Insert the open wake row AND move ``asleep -> waking`` in ONE transaction.

    Returns the new wake id, or None when the agent was not ``asleep`` (the caller joins the running body).
    Raises: sqlite3.IntegrityError when an open wake already exists (``swarm_one_open_wake``), rolled back.
    """
    now = utc_now()
    with transaction(conn):
        wake_id = conn.execute(
            "INSERT INTO swarm_wakes (agent_id, started_at, reason, mode, authority) VALUES (?, ?, ?, ?, ?)",
            (agent_id, now, reason, mode, authority),
        ).lastrowid
        cur = conn.execute(
            "UPDATE swarm_agents SET state = 'waking', updated_at = ? WHERE id = ? AND state = 'asleep'",
            (now, agent_id),
        )
        if cur.rowcount == 0:
            conn.execute("DELETE FROM swarm_wakes WHERE id = ?", (wake_id,))
            return None
    _changed(agent_id)
    return wake_id


def get_open_wake(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_wakes WHERE agent_id = ? AND ended_at IS NULL", (agent_id,)).fetchone())


def update_wake(conn: sqlite3.Connection, wake_id: int, **fields: Any) -> None:
    unknown = set(fields) - _WAKE_UPDATABLE
    if unknown or not fields:
        raise ValueError(f"cannot update {sorted(unknown) or 'nothing'}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    with transaction(conn):
        conn.execute(f"UPDATE swarm_wakes SET {sets} WHERE id = ?", (*fields.values(), wake_id))


def stamp_last_conversation(conn: sqlite3.Connection, agent_id: int) -> None:
    """Record the row's conversation id on the agent's newest wake when that wake has none (call after the wake closed).

    The rewind's conversation list reads ``swarm_wakes.conversation_uuid``; the id lives on the ``sessions`` row, which a
    later fresh wake clears, so each wake is stamped as it ends.
    """
    with transaction(conn):
        conn.execute(
            "UPDATE swarm_wakes SET conversation_uuid = (SELECT s.claude_session_uuid FROM swarm_agents a JOIN sessions s "
            "ON s.id = a.session_row_id WHERE a.id = swarm_wakes.agent_id) "
            "WHERE id = (SELECT MAX(id) FROM swarm_wakes WHERE agent_id = ?) AND ended_at IS NOT NULL AND conversation_uuid IS NULL",
            (agent_id,))


def point_at_conversation(conn: sqlite3.Connection, agent_id: int, wake_id: int, conversation_uuid: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE id = (SELECT session_row_id FROM swarm_agents WHERE id = ?)",
                     (conversation_uuid, agent_id))
        conn.execute("UPDATE swarm_wakes SET conversation_uuid = ? WHERE id = ?", (conversation_uuid, wake_id))


def clear_conversation(conn: sqlite3.Connection, agent_id: int) -> None:
    with transaction(conn):
        conn.execute("UPDATE sessions SET claude_session_uuid = NULL WHERE id = (SELECT session_row_id FROM swarm_agents WHERE id = ?)",
                     (agent_id,))


def close_wake(conn: sqlite3.Connection, wake_id: int, end_reason: str) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE swarm_wakes SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
            (utc_now(), end_reason, wake_id),
        )
    return cur.rowcount == 1


def live_body_count(conn: sqlite3.Connection, parent_id: Optional[int] = None) -> int:
    sql = "SELECT COUNT(*) FROM swarm_wakes w JOIN swarm_agents a ON a.id = w.agent_id WHERE w.ended_at IS NULL"
    args: tuple = ()
    if parent_id is not None:
        sql += " AND a.parent_id = ?"
        args = (parent_id,)
    return int(conn.execute(sql, args).fetchone()[0])


def record_delivery(
    conn: sqlite3.Connection,
    agent_id: int,
    *,
    authority: str,
    source: str,
    wake_id: Optional[int] = None,
    source_ref: Optional[str] = None,
    owner_message_ref: Optional[str] = None,
) -> int:
    with transaction(conn):
        wake_started = _wake_start_for_prompt(conn, agent_id, authority, source, wake_id, source_ref)
        delivery_id = int(
            conn.execute(
                "INSERT INTO swarm_deliveries (agent_id, wake_id, authority, source, source_ref, owner_message_ref,"
                " delivered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_id, wake_id, authority, source, source_ref, owner_message_ref, utc_now()),
            ).lastrowid
        )
    _tell_guard(conn, agent_id, authority, delivery_id, wake_started)
    return delivery_id


def _wake_start_for_prompt(conn: sqlite3.Connection, agent_id: int, authority: str, source: str, wake_id: Optional[int],
                           source_ref: Optional[str]) -> Optional[datetime]:
    if source != "wake_prompt" or wake_id is None or authority != "owner" or source_ref != f"wake:{wake_id}":
        return None
    wake = conn.execute("SELECT started_at FROM swarm_wakes WHERE id = ? AND agent_id = ? AND authority = 'owner' AND ended_at IS NULL",
                        (wake_id, agent_id)).fetchone()
    if wake is None or conn.execute("SELECT 1 FROM swarm_deliveries WHERE wake_id = ? LIMIT 1", (wake_id,)).fetchone():
        return None
    try:
        return datetime.fromisoformat(str(wake["started_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None


def _tell_guard(conn: sqlite3.Connection, agent_id: int, authority: str, delivery_id: int,
                wake_started_at: Optional[datetime] = None) -> None:
    from src.core.swarm import guard

    row = conn.execute("SELECT a.rank, s.tmux_name FROM swarm_agents a LEFT JOIN sessions s ON s.id = a.session_row_id "
                       "WHERE a.id = ?", (agent_id,)).fetchone()
    if row is not None and row["rank"] == "alpha":
        guard.on_delivery(agent_id, authority, datetime.now(timezone.utc), delivery_id, row["tmux_name"] or "",
                          wake_started_at=wake_started_at)


def list_deliveries(conn: sqlite3.Connection, agent_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM swarm_deliveries WHERE agent_id = ? ORDER BY delivered_at DESC, id DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def tear_down(conn: sqlite3.Connection, agent_id: int) -> bool:
    now = utc_now()
    with transaction(conn):
        cur = conn.execute(
            "UPDATE swarm_agents SET state = 'torn_down', torn_down_at = ?, updated_at = ? "
            "WHERE id = ? AND torn_down_at IS NULL",
            (now, now, agent_id),
        )
    if cur.rowcount == 1:
        _changed(agent_id)
    return cur.rowcount == 1


def get_visibility(conn: sqlite3.Connection, repo_dir: str) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_repo_visibility WHERE repo_dir = ?", (repo_dir,)).fetchone())


def upsert_visibility(
    conn: sqlite3.Connection, repo_dir: str, *, visibility: str, remote_url: Optional[str] = None,
    card_ref: Optional[str] = None, remote_fingerprint: Optional[str] = None,
) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO swarm_repo_visibility (repo_dir, remote_url, visibility, checked_at, card_ref,"
            " remote_fingerprint) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(repo_dir) DO UPDATE SET"
            " remote_url = excluded.remote_url, visibility = excluded.visibility,"
            " checked_at = excluded.checked_at,"
            " approved_at = CASE WHEN remote_fingerprint IS excluded.remote_fingerprint"
            "   THEN approved_at ELSE NULL END,"
            " card_ref = CASE WHEN remote_fingerprint IS excluded.remote_fingerprint"
            "   THEN COALESCE(excluded.card_ref, card_ref) ELSE excluded.card_ref END,"
            " remote_fingerprint = excluded.remote_fingerprint",
            (repo_dir, remote_url, visibility, utc_now(), card_ref, remote_fingerprint),
        )


def approve_visibility(conn: sqlite3.Connection, repo_dir: str, remote_fingerprint: str) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE swarm_repo_visibility SET approved_at = ? WHERE repo_dir = ? AND remote_fingerprint = ?",
            (utc_now(), repo_dir, remote_fingerprint),
        )
    return cur.rowcount == 1


def get_agent_by_session_uuid(conn: sqlite3.Connection, session_uuid: str) -> Optional[Dict[str, Any]]:
    return _row(conn.execute(
        "SELECT a.* FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id WHERE s.session_uuid = ?",
        (session_uuid,)).fetchone())


def delete_delivery(conn: sqlite3.Connection, delivery_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM swarm_deliveries WHERE id = ?", (delivery_id,))
    from src.core.swarm import guard

    guard.on_discard(delivery_id)


def last_wake_started_at(conn: sqlite3.Connection, agent_id: int) -> Optional[str]:
    row = conn.execute("SELECT started_at FROM swarm_wakes WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
                       (agent_id,)).fetchone()
    return row[0] if row else None


def get_project_agent(conn: sqlite3.Connection, project_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_agents WHERE rank = 'project' AND project_id = ? AND torn_down_at IS NULL",
                             (project_id,)).fetchone())



def create_report(conn: sqlite3.Connection, agent: Dict[str, Any], summary: str) -> int:
    with transaction(conn):
        return int(conn.execute(
            "INSERT INTO swarm_reports (agent_id, parent_id, task_type, summary, state, created_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?)", (agent["id"], agent["parent_id"], agent.get("task_type"), summary, utc_now())).lastrowid)


def get_report(conn: sqlite3.Connection, report_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_reports WHERE id = ?", (report_id,)).fetchone())


def list_reports(conn: sqlite3.Connection, *, parent_id: Optional[int] = None, agent_id: Optional[int] = None,
                 state: str = "pending") -> List[Dict[str, Any]]:
    where, args = ["state = ?"], [state]
    for column, value in (("parent_id", parent_id), ("agent_id", agent_id)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    return [dict(r) for r in conn.execute(f"SELECT * FROM swarm_reports WHERE {' AND '.join(where)} ORDER BY id", args).fetchall()]


def set_report_cards(conn: sqlite3.Connection, report_id: int, child_card_ref: Optional[str], parent_card_ref: Optional[str]) -> None:
    with transaction(conn):
        conn.execute("UPDATE swarm_reports SET child_card_ref = ?, parent_card_ref = ? WHERE id = ?",
                     (child_card_ref, parent_card_ref, report_id))


def decide_report(conn: sqlite3.Connection, report_id: int, new: str, expected: str = "pending") -> bool:
    with transaction(conn):
        cur = conn.execute("UPDATE swarm_reports SET state = ?, decided_at = ? WHERE id = ? AND state = ?",
                           (new, None if new == "pending" else utc_now(), report_id, expected))
    return cur.rowcount == 1


def delete_report(conn: sqlite3.Connection, report_id: int) -> None:
    """Remove a report whose cards could not be posted, so the child may report again."""
    with transaction(conn):
        conn.execute("DELETE FROM swarm_reports WHERE id = ?", (report_id,))
