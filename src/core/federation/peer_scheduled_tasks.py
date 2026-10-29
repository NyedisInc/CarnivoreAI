
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Callable, List, Tuple

import structlog

from src.core.federation import peer_hosts
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.models.scheduled_tasks import PeerTasksState, ScheduledTask, ScheduledTasksList

logger = structlog.get_logger(__name__)


async def _ask(row: peer_hosts.PeerRow, client: Any) -> Tuple[PeerTasksState, List[ScheduledTask]]:
    down = PeerTasksState(host_key=row.key, host_label=row.label, state="peer_unavailable")
    try:
        reply = await client.request("GET", "/scheduled-tasks")
        if reply.status_code != 200:
            return down, []
        tasks = [ScheduledTask(**{**t, "host_key": row.key, "host_label": row.label})
                 for t in ScheduledTasksList(**reply.json()).model_dump()["tasks"]]
    except (PeerUnreachable, PeerRefused, ValueError, TypeError) as exc:
        logger.info("peer_scheduled_tasks_unavailable", peer=row.key, error=str(exc)[:120])
        return down, []
    return PeerTasksState(host_key=row.key, host_label=row.label, state="ok", total=len(tasks)), tasks


async def merge(local: ScheduledTasksList, open_db: Callable[[], sqlite3.Connection], links: Any) -> ScheduledTasksList:
    if links is None:
        return local

    def rows() -> List[peer_hosts.PeerRow]:
        with closing(open_db()) as conn:
            return peer_hosts.list_peers(conn)

    try:
        peers = await asyncio.to_thread(rows)
    except sqlite3.Error as exc:
        logger.warning("peer_scheduled_tasks_read_failed", error=str(exc)[:120])
        return local
    answers = await asyncio.gather(*(_ask(r, links.client(r.peer_install_id)) if links.client(r.peer_install_id)
                                     else _skip(r) for r in peers))
    merged = local.model_copy(update={"peers": [state for state, _ in answers]})
    merged.tasks = [*local.tasks, *(t for _, tasks in answers for t in tasks)]
    return merged


async def _skip(row: peer_hosts.PeerRow) -> Tuple[PeerTasksState, List[ScheduledTask]]:
    return PeerTasksState(host_key=row.key, host_label=row.label, state="peer_unavailable"), []
