
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Iterable, List

import structlog

from src.core import resource_push
from src.core.resource_push import topics

logger = structlog.get_logger()


def notify_roster() -> None:
    resource_push.notify(topics.SWARM_ROSTER)


def notify_agent(agent_id: int) -> None:
    resource_push.notify(topics.keyed(topics.SWARM_AGENT, str(int(agent_id))))


DRAFT_INTERVAL_S = 1.0


def notify_agent_draft(agent_id: int) -> None:
    key = str(int(agent_id))
    resource_push.notify_coalesced(topics.keyed(topics.SWARM_AGENT, key), f"draft:{key}", DRAFT_INTERVAL_S)


def agent_ids_for_keys(session_uuids: Iterable[str]) -> List[int]:
    keys = [k for k in session_uuids if isinstance(k, str) and k]
    if not keys:
        return []
    from src.config import settings
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    marks = ",".join("?" for _ in keys)
    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            rows = conn.execute(
                "SELECT a.id FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
                f"WHERE s.session_uuid IN ({marks})", keys).fetchall()
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_push_keys_unreadable", error_type=type(exc).__name__)
        return []
    return [int(r[0]) for r in rows]


def notify_thread(thread_key: str) -> None:
    from src.config import settings
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            row = conn.execute("SELECT id FROM swarm_agents WHERE thread_key = ? AND torn_down_at IS NULL",
                               (thread_key,)).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_push_thread_unreadable", error_type=type(exc).__name__)
        return
    if row is not None:
        notify_agent(int(row[0]))


def notify_keys(*session_uuids: str) -> List[int]:
    ids = agent_ids_for_keys(session_uuids)
    for agent_id in ids:
        notify_agent(agent_id)
    return ids
