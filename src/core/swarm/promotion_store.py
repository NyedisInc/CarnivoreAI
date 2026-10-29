
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.core.db import transaction
from src.core.swarm import push, store
from src.core.trail_entry import utc_now

DEFAULT_PROMOTION_THRESHOLD = 5


def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def _changed(agent_id: int) -> None:
    push.notify_roster()
    push.notify_agent(agent_id)


def promotion_threshold(conn: sqlite3.Connection, project_id: Optional[int]) -> int:
    row = conn.execute("SELECT promotion_threshold FROM swarm_project_settings WHERE project_id = ?", (project_id,)).fetchone()
    return int(row[0]) if row else DEFAULT_PROMOTION_THRESHOLD


def set_promotion_threshold(conn: sqlite3.Connection, project_id: int, value: int) -> int:
    with transaction(conn):
        conn.execute("INSERT INTO swarm_project_settings (project_id, promotion_threshold) VALUES (?, ?) "
                     "ON CONFLICT(project_id) DO UPDATE SET promotion_threshold = excluded.promotion_threshold", (project_id, value))
    return value


def promotion_standing(conn: sqlite3.Connection, child: Dict[str, Any]) -> Tuple[int, int]:
    parent = store.get_agent(conn, child["parent_id"]) if child.get("parent_id") is not None else None
    project_id, task_type = (parent or {}).get("project_id"), child.get("task_type")
    threshold = promotion_threshold(conn, project_id)
    if project_id is None or not task_type:
        return 0, threshold
    count = conn.execute(
        "SELECT COUNT(*) FROM swarm_reports r JOIN swarm_agents p ON p.id = r.parent_id WHERE r.state = 'accepted' "
        "AND r.task_type = ? AND p.project_id = ? AND r.decided_at > COALESCE((SELECT MAX(flipped_back_at) "
        "FROM swarm_promotions WHERE project_id = ? AND task_type = ?), '')", (task_type, project_id, project_id, task_type)).fetchone()[0]
    return int(count), threshold


def promotion_earned(conn: sqlite3.Connection, child: Dict[str, Any]) -> bool:
    count, threshold = promotion_standing(conn, child)
    return bool(child.get("task_type")) and count >= threshold and promoted_agent(conn, child["parent_id"], child["task_type"]) is None


def create_promotion(conn: sqlite3.Connection, agent: Dict[str, Any], project_id: Optional[int], commit_sha: str, seed_rel_path: str) -> int:
    with transaction(conn):
        return int(conn.execute(
            "INSERT INTO swarm_promotions (agent_id, project_id, task_type, from_rank, to_rank, commit_sha, seed_rel_path, created_at)"
            " VALUES (?, ?, ?, 'task', 'feature', ?, ?, ?)",
            (agent["id"], project_id, agent["task_type"], commit_sha or None, seed_rel_path, utc_now())).lastrowid)


def get_promotion(conn: sqlite3.Connection, promotion_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_promotions WHERE id = ?", (promotion_id,)).fetchone())


def live_promotion(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    return _row(conn.execute("SELECT * FROM swarm_promotions WHERE agent_id = ? AND flipped_back_at IS NULL ORDER BY id DESC LIMIT 1",
                             (agent_id,)).fetchone())


def set_promotion_card(conn: sqlite3.Connection, promotion_id: int, card_ref: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE swarm_promotions SET receipt_card_ref = ? WHERE id = ?", (card_ref, promotion_id))


def mark_flipped_back(conn: sqlite3.Connection, promotion_id: int, flip_commit_sha: str) -> bool:
    with transaction(conn):
        cur = conn.execute("UPDATE swarm_promotions SET flipped_back_at = ?, flip_commit_sha = ? WHERE id = ? AND flipped_back_at IS NULL",
                           (utc_now(), flip_commit_sha or None, promotion_id))
    return cur.rowcount == 1


def promoted_agent(conn: sqlite3.Connection, parent_id: int, task_type: str) -> Optional[Dict[str, Any]]:
    return _row(conn.execute(
        "SELECT a.* FROM swarm_promotions pr JOIN swarm_agents a ON a.id = pr.agent_id WHERE pr.flipped_back_at IS NULL "
        "AND pr.task_type = ? AND a.parent_id = ? AND a.rank = 'feature' AND a.torn_down_at IS NULL ORDER BY pr.id DESC LIMIT 1",
        (task_type, parent_id)).fetchone())


def set_shape(conn: sqlite3.Connection, agent_id: int, rank: str, memory_scope: str) -> Dict[str, Any]:
    if (rank, memory_scope) not in (("task", "local"), ("feature", "project")):
        raise ValueError(f"cannot reshape an agent to {rank} with {memory_scope} memory")
    with transaction(conn):
        cur = conn.execute("UPDATE swarm_agents SET rank = ?, memory_scope = ?, updated_at = ? WHERE id = ? AND rank IN ('task', 'feature')",
                           (rank, memory_scope, utc_now(), agent_id))
        if cur.rowcount == 0:
            raise store.AgentNotFound(agent_id)
    _changed(agent_id)
    return store.get_agent(conn, agent_id) or {}


def reshaped_since_last_wake(conn: sqlite3.Connection, agent_id: int) -> bool:
    row = conn.execute("SELECT MAX(MAX(created_at), COALESCE(MAX(flipped_back_at), '')) FROM swarm_promotions WHERE agent_id = ?",
                       (agent_id,)).fetchone()
    return bool(row and row[0] and row[0] > (store.last_wake_started_at(conn, agent_id) or ""))


def seed_pending(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    promo = live_promotion(conn, agent_id)
    if promo is None or not promo.get("seed_rel_path"):
        return None
    since = conn.execute("SELECT COUNT(*) FROM swarm_wakes WHERE agent_id = ? AND started_at >= ?", (agent_id, promo["created_at"])).fetchone()[0]
    return promo if since <= 1 else None


def promotions_naming(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT pr.*, a.display_name AS agent_name, COALESCE(p.display_name, 'a parent') AS parent_name FROM swarm_promotions pr "
        "JOIN swarm_agents a ON a.id = pr.agent_id LEFT JOIN swarm_agents p ON p.id = a.parent_id "
        "WHERE pr.agent_id = ? OR a.parent_id = ? ORDER BY pr.id DESC LIMIT ?", (agent_id, agent_id, limit)).fetchall()]
