
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, Tuple

import structlog

from src.core import db

logger = structlog.get_logger()

FIELDS: Tuple[Tuple[str, str], ...] = (("id", "swarm_agent_id"), ("rank", "swarm_rank"), ("character_seed", "swarm_character_seed"),
                                       ("color_slot", "swarm_color_slot"))


def bound_agents(conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
    if not db.table_exists(conn, "swarm_agents"):
        return {}
    rows = conn.execute("SELECT session_row_id, id, rank, character_seed, color_slot FROM swarm_agents "
                        "WHERE session_row_id IS NOT NULL AND torn_down_at IS NULL").fetchall()
    return {int(r[0]): {"id": r[1], "rank": r[2], "character_seed": r[3], "color_slot": r[4]} for r in rows}


async def mark_swarm_members(rows: Iterable[Any], row_attr: str = "session_row_id") -> None:
    from src.core.swarm import body

    rows = list(rows)
    if not rows:
        return
    try:
        bound = await body.run_db(bound_agents)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_member_listing_unreadable", error_type=type(exc).__name__)
        bound = {}
    for row in rows:
        agent = bound.get(getattr(row, row_attr, None))
        for column, field in FIELDS:
            if hasattr(row, field):
                setattr(row, field, agent[column] if agent else None)
