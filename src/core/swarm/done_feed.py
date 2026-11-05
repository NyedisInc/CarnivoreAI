
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Set

import structlog

from src.core.swarm import body, push
from src.core.swarm.stream_sources import event_entry

logger = structlog.get_logger()

LEVEL_SQL = "COALESCE(i.card_level, CASE WHEN i.card_parent IS NULL THEN 'feature' ELSE 'task' END)"
_DONE_SQL = (
    "SELECT e.item_id AS id, MIN(e.at) AS at, i.list_key, i.card_parent, " + LEVEL_SQL + " AS level, "
    "COALESCE(NULLIF(i.card_summary, ''), NULLIF(i.title, ''), i.text) AS summary, "
    "COALESCE(h.display_name, '') AS agent_name "
    "FROM work_card_events e JOIN work_items i ON i.id = e.item_id "
    "LEFT JOIN swarm_agents h ON h.id = COALESCE(i.card_holder, i.card_last_holder) "
    "WHERE e.kind IN ('done', 'accepted') AND e.to_col = 'done' AND i.deleted = 0 AND i.swarm_ref = '' "
    "AND i.kind NOT IN ('question', 'info') AND {scope} GROUP BY e.item_id ORDER BY at DESC LIMIT ?")
RECENT_S = 30.0
_pushed: Set[int] = set()


def line(agent_name: str, summary: str) -> str:
    words = " ".join((summary or "").strip().split("\n", 1)[0].split())[:200]
    return f"{agent_name}: {words}, done" if agent_name else f"{words}, done"


def _scope(agent: Dict[str, Any]) -> Optional[tuple]:
    rank = agent.get("rank")
    if rank == "project":
        return "i.list_key = ?", (str(agent["thread_key"]),)
    if rank == "company":
        return (f"{LEVEL_SQL} = 'feature' AND (i.list_key = ? OR i.list_key IN "
                "(SELECT CAST(id AS TEXT) FROM projects WHERE company_id = ?))"), (str(agent["thread_key"]), agent.get("company_id"))
    if rank == "alpha":
        return f"{LEVEL_SQL} = 'feature'", ()
    return None


def rows(conn: sqlite3.Connection, agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    scope = _scope(agent)
    if scope is None:
        return []
    sql, args = scope
    found = conn.execute(_DONE_SQL.format(scope=sql), (*args, int(limit))).fetchall()
    return [event_entry("done", r["at"], f"card:{r['id']}", line(r["agent_name"], r["summary"] or ""), card_id=r["id"], level=r["level"])
            for r in found]


async def done_entries(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    try:
        return await body.run_db(lambda c: rows(c, agent, limit))
    except sqlite3.OperationalError as exc:
        logger.warning("swarm_done_lines_unreadable", agent_id=agent.get("id"), error_type=type(exc).__name__)
        return []


def for_agents(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in entries if not (e.get("kind") == "event" and e.get("event") == "done")]


def upward_agents(conn: sqlite3.Connection, list_key: str, now: Optional[float] = None) -> List[int]:
    since = (time.time() if now is None else now) - RECENT_S
    fresh = [r for r in conn.execute(
        "SELECT e.id FROM work_card_events e JOIN work_items i ON i.id = e.item_id WHERE e.list_key = ? AND e.at >= ? "
        f"AND e.kind IN ('done', 'accepted') AND e.to_col = 'done' AND {LEVEL_SQL} = 'feature'", (list_key, since)).fetchall()
        if r[0] not in _pushed]
    if not fresh:
        return []
    _pushed.update(r[0] for r in fresh)
    company = conn.execute("SELECT company_id FROM projects WHERE CAST(id AS TEXT) = ?", (list_key,)).fetchone()
    found = conn.execute(
        "SELECT id FROM swarm_agents WHERE torn_down_at IS NULL AND (rank = 'alpha' OR (rank = 'company' AND (thread_key = ? OR company_id = ?)))",
        (list_key, company[0] if company else None)).fetchall()
    return [int(r[0]) for r in found]


def notify_upward(conn: sqlite3.Connection, list_key: str) -> None:
    try:
        targets = upward_agents(conn, list_key)
    except sqlite3.Error as exc:
        logger.warning("swarm_done_push_unreadable", list_key=list_key, error_type=type(exc).__name__)
        return
    for agent_id in targets:
        push.notify_agent(agent_id)
